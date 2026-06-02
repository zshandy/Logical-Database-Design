import os
import re
import ast
import time
import argparse
import logging
import pandas as pd
import json
import glob
from func_timeout import func_set_timeout, FunctionTimedOut
import sqlite3

from typing import List, Tuple, Union
from langchain.sql_database import SQLDatabase
from langchain.chat_models import ChatOpenAI
from langchain.chains import LLMChain
from langchain.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)
from openai import OpenAI

# All lazy-initialized inside main() so importing this module does not
# require API keys to be set in the importer's environment.
CHAT = None            # langchain ChatOpenAI, used only for stage 1 (schema linking)
client = None          # openai.OpenAI client (for --model gpt)
gemini_client = None   # Google GenAI client (for --model gemini)


def ensure_openai():
    """Lazy-init OpenAI client + LangChain CHAT."""
    global CHAT, client
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY environment variable is not set.")
    if client is None:
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    if CHAT is None:
        CHAT = ChatOpenAI(
            model="gpt-4.1-mini", temperature=0, max_tokens=10000,
            openai_api_key=os.environ["OPENAI_API_KEY"],
        )


def ensure_gemini():
    """Lazy-init Google GenAI client."""
    global gemini_client
    if gemini_client is None:
        from google import genai
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise SystemExit("GEMINI_API_KEY environment variable is not set.")
        gemini_client = genai.Client(api_key=api_key)


def chat_with_chatgpt_DIN(prompt, model="gpt-4.1-mini"):
    """Direct call to the openai client."""
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        n=1, stream=False, temperature=0.0, max_completion_tokens=10000,
        top_p=1.0, frequency_penalty=0.0, presence_penalty=0.0,
    )
    return response.choices[0].message.content


def chat_with_gemini_DIN(prompt, model="gemini-2.5-flash-lite", response_fields=None):
    """Call Gemini. If response_fields is provided (e.g. {"SQL": str}), use structured output."""
    from google.genai import types
    from pydantic import create_model

    config_kwargs = dict(temperature=0.0, max_output_tokens=10000, top_p=1.0)
    if response_fields:
        schema_model = create_model("DynResponse", **{k: (v, ...) for k, v in response_fields.items()})
        config_kwargs["response_mime_type"] = "application/json"
        config_kwargs["response_schema"] = schema_model

    response = gemini_client.models.generate_content(
        model=model, contents=prompt,
        config=types.GenerateContentConfig(**config_kwargs),
    )
    return response.text


def append_log(log_dir: str, index: int, section: str, body: str) -> None:
    """Append a labeled section to the per-question log file."""
    fp = os.path.join(log_dir, f"q{int(index):04d}.log")
    with open(fp, "a", encoding="utf-8") as f:
        f.write(f"\n===== {section} =====\n")
        f.write(body if body is not None else "")
        f.write("\n")


def load_rename_mapping(mapping_path: str, org_keyed_columns: bool = False):
    """Load a name-mapping JSON and return:
       table_to_view:        {org_table_lower: renamed_view}  (case-insensitive keys)
       view_org_to_renamed:  {renamed_view: {org_col_lower: renamed_col}}

    org_keyed_columns: controls how the inner column dict is interpreted.
      False (spider): inner dict is {renamed_col: org_col}
      True  (bird):   inner dict is {org_col: renamed_col}
    """
    with open(mapping_path, encoding="utf-8") as f:
        m = json.load(f)
    table_to_view = {k.lower(): v for k, v in m["table_to_view"].items()}
    column_mapping = m["column_mapping"]
    view_org_to_renamed = {}
    for view, cols in column_mapping.items():
        if org_keyed_columns:
            view_org_to_renamed[view] = {k.lower(): v for k, v in cols.items()}
        else:
            view_org_to_renamed[view] = {v.lower(): k for k, v in cols.items()}
    return table_to_view, view_org_to_renamed


def fetch_org_fks(db_path: str, org_tables):
    """Return a list of (from_table, from_col, ref_table, ref_col) tuples for FKs
    declared between tables in `org_tables`. Reads PRAGMA foreign_key_list.
    """
    org_lower = {t.lower(): t for t in org_tables}
    out = []
    seen = set()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    try:
        for t in org_tables:
            try:
                rows = cur.execute(f"PRAGMA foreign_key_list('{t}')").fetchall()
            except sqlite3.DatabaseError:
                continue
            for row in rows:
                ref_table = row[2]
                from_col = row[3]
                to_col = row[4]
                if not ref_table or not from_col or not to_col:
                    continue
                if ref_table.lower() not in org_lower:
                    continue
                key = (t.lower(), from_col.lower(), ref_table.lower(), to_col.lower())
                if key in seen:
                    continue
                seen.add(key)
                out.append((t, from_col, ref_table, to_col))
    finally:
        conn.close()
    return out


def build_renamed_fk_block(db_path: str, org_tables, mapping_path: str,
                           org_keyed_columns: bool = False) -> str:
    """Translate each FK declared between `org_tables` into the renamed namespace
    and return a 'Foreign Keys:' block string.

    org_keyed_columns: passed through to load_rename_mapping (False=spider, True=bird).
    Returns "" if no FKs translate cleanly.
    """
    table_to_view, view_org_to_renamed = load_rename_mapping(mapping_path, org_keyed_columns)
    fks = fetch_org_fks(db_path, org_tables)

    lines = []
    skipped = []
    for from_t, from_c, ref_t, ref_c in fks:
        from_view = table_to_view.get(from_t.lower())
        ref_view = table_to_view.get(ref_t.lower())
        if not from_view or not ref_view:
            skipped.append((from_t, from_c, ref_t, ref_c, "table not in mapping"))
            continue
        from_renamed = view_org_to_renamed.get(from_view, {}).get(from_c.lower())
        ref_renamed = view_org_to_renamed.get(ref_view, {}).get(ref_c.lower())
        if not from_renamed or not ref_renamed:
            skipped.append((from_t, from_c, ref_t, ref_c, "column not in mapping"))
            continue
        lines.append(f"{from_view}.{from_renamed} = {ref_view}.{ref_renamed}")

    if skipped:
        print(f"⚠️  {len(skipped)}/{len(fks)} FK lines could not be translated:")
        for s in skipped[:10]:
            print(f"     {s}")
        if len(skipped) > 10:
            print(f"     ... and {len(skipped) - 10} more")

    if not lines:
        return ""

    return "Foreign Keys:\n" + "\n".join(sorted(set(lines))) + "\n\n"


def parse_view_base_tables(view_name: str):
    """Extract base tables from a view name. Handles three shapes:
      - 'cluster<N>_<t1>_join_<t2>(_join_<tN>)*'
      - 'workload_updated_cluster<N>_<t1>_join_<t2>(_join_<tN>)*'
      - bare '<t1>_join_<t2>(_join_<tN>)*'  (no cluster prefix, e.g. bird_org_views_50)
    An optional trailing '_view' (single-table views like 'income_view') is stripped.
    """
    m = re.match(r'^(?:workload_updated_)?cluster\d+_(.+)$', view_name)
    core = m.group(1) if m else view_name
    if core.endswith('_view'):
        core = core[: -len('_view')]
    return core.split('_join_') if core else []


def find_matching_views(views_pool, retrieved_tables):
    """Return all views from the pool that contain at least one of retrieved_tables."""
    rt_lower = {str(t).lower() for t in retrieved_tables}
    out = []
    for v in views_pool:
        bases = parse_view_base_tables(v)
        if any(b.lower() in rt_lower for b in bases):
            out.append(v)
    return out


def parse_retrieved_tables_from_links(schema_links):
    """Parse schema_links (list or stringified list) → set of table names (lowercase)."""
    sl_raw = schema_links
    if isinstance(sl_raw, str):
        sl_raw = ast.literal_eval(sl_raw)
    temp_list = [x.replace('`', '').lower() for x in sl_raw if isinstance(x, str)]
    col_list = []
    for i in temp_list:
        if len(i.split(".")) == 2 and "=" not in i:
            col_list.append(i)
        elif len(i.split("=")) == 2:
            t = i.split("=")
            if len(t[0].strip().split(".")) == 2:
                col_list.append(t[0].strip())
            if len(t[1].strip().split(".")) == 2:
                col_list.append(t[1].strip())
    return list({x.split(".")[0] for x in col_list if len(x.split(".")) == 2})


def apply_row_selection(df, spec):
    """Slice df according to --rows. 'N' → first N; 'START:END' → iloc[START:END]."""
    if spec is None:
        return df
    if ":" in spec:
        a, b = spec.split(":", 1)
        start = int(a) if a.strip() else 0
        end = int(b) if b.strip() else len(df)
        return df.iloc[start:end]
    return df.iloc[: int(spec)]

SYSTEM_SCHEMA_LINKING_TEMPLATE = """
You are an agent designed to find the schema_links for generating SQL queries for each question based on the database schema and Foreign keys.
Hint helps you to fine the correct schema_links.
###
Few examples of this task are:
###
Schema of the database with sample rows and column descriptions:
#
CREATE TABLE movies (
        movie_id INTEGER NOT NULL, 
        movie_title TEXT, 
        movie_release_year INTEGER, 
        movie_url TEXT, 
        movie_title_language TEXT, 
        movie_popularity INTEGER, 
        movie_image_url TEXT, 
        director_id TEXT, 
        director_name TEXT, 
        director_url TEXT, 
        PRIMARY KEY (movie_id)
)

/*
3 rows from movies table:
movie_id        movie_title     movie_release_year      movie_url       movie_title_language    movie_popularity        movie_image_url director_id     director_namedirector_url
1       La Antena       2007    http://mubi.com/films/la-antena en      105     https://images.mubicdn.net/images/film/1/cache-7927-1581389497/image-w1280.jpg  131  Esteban Sapir    http://mubi.com/cast/esteban-sapir
2       Elementary Particles    2006    http://mubi.com/films/elementary-particles      en      23      https://images.mubicdn.net/images/film/2/cache-512179-1581389841/image-w1280.jpg      73      Oskar Roehler   http://mubi.com/cast/oskar-roehler
3       It's Winter     2006    http://mubi.com/films/its-winter        en      21      https://images.mubicdn.net/images/film/3/cache-7929-1481539519/image-w1280.jpg82      Rafi Pitts      http://mubi.com/cast/rafi-pitts
*/

CREATE TABLE ratings (
        movie_id INTEGER, 
        rating_id INTEGER, 
        rating_url TEXT, 
        rating_score INTEGER, 
        rating_timestamp_utc TEXT, 
        critic TEXT, 
        critic_likes INTEGER, 
        critic_comments INTEGER, 
        user_id INTEGER, 
        user_trialist INTEGER, 
        user_subscriber INTEGER, 
        user_eligible_for_trial INTEGER, 
        user_has_payment_method INTEGER, 
        FOREIGN KEY(movie_id) REFERENCES movies (movie_id), 
        FOREIGN KEY(user_id) REFERENCES lists_users (user_id), 
        FOREIGN KEY(rating_id) REFERENCES ratings (rating_id), 
        FOREIGN KEY(user_id) REFERENCES ratings_users (user_id)
)

/*
3 rows from ratings table:
movie_id        rating_id       rating_url      rating_score    rating_timestamp_utc    critic  critic_likes    critic_comments user_id user_trialist   user_subscriber       user_eligible_for_trial user_has_payment_method
1066    15610495        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/15610495 3       2017-06-10 12:38:33     None    0       0       41579158     00       1       0
1066    10704606        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10704606 2       2014-08-15 23:42:31     None    0       0       85981819     11       0       1
1066    10177114        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10177114 2       2014-01-30 13:21:57     None    0       0       4208563 0    01       1
*/
#
Q: Which year has the least number of movies that was released and what is the title of the movie in that year that has the highest number of rating score of 1?
Please respond with a JSON object structured as follows:
A: {{"chain_of_thought_reasoning": "Let’s think step by step. In the question , we are asked:
"Which year" so we need column = [movies.movie_release_year]
"number of movies" so we need column = [movies.movie_id]
"title of the movie" so we need column = [movies.movie_title]
"rating score" so we need column = [ratings.rating_score]
Based on the columns and tables, we need these Foreign_keys = [movies.movie_id = ratings.movie_id].
Based on the tables, columns, and Foreign_keys, The set of possible cell values are = [1].",
"schema_links": [`movies`.`movie_release_year`, `movies`.`movie_title`, `ratings`.`rating_score`, `movies`.`movie_id`=`ratings`.`movie_id`, 1]}}

Schema of the database with sample rows:
#
CREATE TABLE lists (
        user_id INTEGER, 
        list_id INTEGER NOT NULL, 
        list_title TEXT, 
        list_movie_number INTEGER, 
        list_update_timestamp_utc TEXT, 
        list_creation_timestamp_utc TEXT, 
        list_followers INTEGER, 
        list_url TEXT, 
        list_comments INTEGER, 
        list_description TEXT, 
        list_cover_image_url TEXT, 
        list_first_image_url TEXT, 
        list_second_image_url TEXT, 
        list_third_image_url TEXT, 
        PRIMARY KEY (list_id), 
        FOREIGN KEY(user_id) REFERENCES lists_users (user_id)
)

/*
3 rows from lists table:
user_id list_id list_title      list_movie_number       list_update_timestamp_utc       list_creation_timestamp_utc     list_followers  list_url        list_commentslist_description list_cover_image_url    list_first_image_url    list_second_image_url   list_third_image_url
88260493        1       Films that made your kid sister cry     5       2019-01-24 19:16:18     2009-11-11 00:02:21     5       http://mubi.com/lists/films-that-made-your-kid-sister-cry     3       <p>Don’t be such a baby!!</p>
<p><strong>bold</strong></p>    https://assets.mubicdn.net/images/film/3822/image-w1280.jpg?1445914994  https://assets.mubicdn.net/images/film/3822/image-w320.jpg?1445914994 https://assets.mubicdn.net/images/film/506/image-w320.jpg?1543838422    https://assets.mubicdn.net/images/film/485/image-w320.jpg?1575331204
45204418        2       Headscratchers  3       2018-12-03 15:12:20     2009-11-11 00:05:11     1       http://mubi.com/lists/headscratchers    2       <p>Films that need at least two viewings to really make sense.</p>
<p>Or at least… they did for <em>       https://assets.mubicdn.net/images/film/4343/image-w1280.jpg?1583331932  https://assets.mubicdn.net/images/film/4343/image-w320.jpg?1583331932 https://assets.mubicdn.net/images/film/159/image-w320.jpg?1548864573    https://assets.mubicdn.net/images/film/142/image-w320.jpg?1544094102
48905025        3       Sexy Time Movies        7       2019-05-30 03:00:07     2009-11-11 00:20:00     6       http://mubi.com/lists/sexy-time-movies  5       <p>Films that get you in the mood…for love. In development.</p>
<p>Remarks</p>
<p><strong>Enter the    https://assets.mubicdn.net/images/film/3491/image-w1280.jpg?1564112978  https://assets.mubicdn.net/images/film/3491/image-w320.jpg?1564112978https://assets.mubicdn.net/images/film/2377/image-w320.jpg?1564675204    https://assets.mubicdn.net/images/film/2874/image-w320.jpg?1546574412
*/

CREATE TABLE lists_users (
        user_id INTEGER NOT NULL, 
        list_id INTEGER NOT NULL, 
        list_update_date_utc TEXT, 
        list_creation_date_utc TEXT, 
        user_trialist INTEGER, 
        user_subscriber INTEGER, 
        user_avatar_image_url TEXT, 
        user_cover_image_url TEXT, 
        user_eligible_for_trial TEXT, 
        user_has_payment_method TEXT, 
        PRIMARY KEY (user_id, list_id), 
        FOREIGN KEY(list_id) REFERENCES lists (list_id), 
        FOREIGN KEY(user_id) REFERENCES lists (user_id)
)

/*
3 rows from lists_users table:
user_id list_id list_update_date_utc    list_creation_date_utc  user_trialist   user_subscriber user_avatar_image_url   user_cover_image_url    user_eligible_for_trial       user_has_payment_method
85981819        1969    2019-11-26      2009-12-18      1       1       https://assets.mubicdn.net/images/avatars/74983/images-w150.jpg?1523895214      None    0    1
85981819        3946    2020-05-01      2010-01-30      1       1       https://assets.mubicdn.net/images/avatars/74983/images-w150.jpg?1523895214      None    0    1
85981819        6683    2020-04-12      2010-03-31      1       1       https://assets.mubicdn.net/images/avatars/74983/images-w150.jpg?1523895214      None    0    1
*/
#
Q: Among the lists created by user 4208563, which one has the highest number of followers? Indicate how many followers it has and whether the user was a subscriber or not when he created the list.
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let’s think step by step. In the question , we are asked:
"user" so we need column = [lists_users.user_id]
"number of followers" so we need column = [lists.list_followers]
"user was a subscriber or not" so we need column = [lists_users.user_subscriber]
Hint also refers to the columns = [lists_users.user_id,lists.list_followers,lists_users.user_subscriber]
Based on the columns and tables, we need these Foreign_keys = [lists.user_id = lists_user.user_id,lists.list_id = lists_user.list_id].
Based on the tables, columns, and Foreign_keys, The set of possible cell values are = [1, 4208563].", 
"schema_links": [`lists`.`list_followers`,`lists_users`.`user_subscriber`,`lists`.`user_id` = `lists_user`.`user_id`,`lists`.`list_id` = `lists_user`.`list_id`, `lists_users`.`user_id`, 4208563, 1]}}
"""  # noqa: E501
HUMAN_SCHEMA_LINKING_TEMPLATE = """
For the given question, find the schema links between the question and the table.
###
Schema of the database with sample rows and column descriptions:
#
{schema}

#
Q: {question}
A: Let's think step by step. In the question , we are asked:
"""

SYSTEM_CLASSIFICATION_TEMPLATE = """
For the given question, classify it as EASY, NON-NESTED, or NESTED based on nested queries and JOIN.
if need nested queries: predict NESTED
elif need JOIN and don't need nested queries: predict NON-NESTED
elif don't need JOIN and don't need nested queries: predict EASY
Note: Don't mistake the WHERE conditions with nested queries.
Note: Only predict NESTED if the question needs nested queries, if it can be solved with JOIN, predict NON-NESTED.
###
Few examples of this task are:
###
Schema of the database with sample rows and column descriptions:
#
CREATE TABLE lists (
        user_id INTEGER, 
        list_id INTEGER NOT NULL, 
        list_title TEXT, 
        list_movie_number INTEGER, 
        list_update_timestamp_utc TEXT, 
        list_creation_timestamp_utc TEXT, 
        list_followers INTEGER, 
        list_url TEXT, 
        list_comments INTEGER, 
        list_description TEXT, 
        list_cover_image_url TEXT, 
        list_first_image_url TEXT, 
        list_second_image_url TEXT, 
        list_third_image_url TEXT, 
        PRIMARY KEY (list_id), 
        FOREIGN KEY(user_id) REFERENCES lists_users (user_id)
)

/*
3 rows from lists table:
user_id list_id list_title      list_movie_number       list_update_timestamp_utc       list_creation_timestamp_utc     list_followers  list_url        list_commentslist_description list_cover_image_url    list_first_image_url    list_second_image_url   list_third_image_url
88260493        1       Films that made your kid sister cry     5       2019-01-24 19:16:18     2009-11-11 00:02:21     5       http://mubi.com/lists/films-that-made-your-kid-sister-cry     3       <p>Don’t be such a baby!!</p>
<p><strong>bold</strong></p>    https://assets.mubicdn.net/images/film/3822/image-w1280.jpg?1445914994  https://assets.mubicdn.net/images/film/3822/image-w320.jpg?1445914994 https://assets.mubicdn.net/images/film/506/image-w320.jpg?1543838422    https://assets.mubicdn.net/images/film/485/image-w320.jpg?1575331204
45204418        2       Headscratchers  3       2018-12-03 15:12:20     2009-11-11 00:05:11     1       http://mubi.com/lists/headscratchers    2       <p>Films that need at least two viewings to really make sense.</p>
<p>Or at least… they did for <em>       https://assets.mubicdn.net/images/film/4343/image-w1280.jpg?1583331932  https://assets.mubicdn.net/images/film/4343/image-w320.jpg?1583331932 https://assets.mubicdn.net/images/film/159/image-w320.jpg?1548864573    https://assets.mubicdn.net/images/film/142/image-w320.jpg?1544094102
48905025        3       Sexy Time Movies        7       2019-05-30 03:00:07     2009-11-11 00:20:00     6       http://mubi.com/lists/sexy-time-movies  5       <p>Films that get you in the mood…for love. In development.</p>
<p>Remarks</p>
<p><strong>Enter the    https://assets.mubicdn.net/images/film/3491/image-w1280.jpg?1564112978  https://assets.mubicdn.net/images/film/3491/image-w320.jpg?1564112978https://assets.mubicdn.net/images/film/2377/image-w320.jpg?1564675204    https://assets.mubicdn.net/images/film/2874/image-w320.jpg?1546574412
*/


CREATE TABLE lists_users (
        user_id INTEGER NOT NULL, 
        list_id INTEGER NOT NULL, 
        list_update_date_utc TEXT, 
        list_creation_date_utc TEXT, 
        user_trialist INTEGER, 
        user_subscriber INTEGER, 
        user_avatar_image_url TEXT, 
        user_cover_image_url TEXT, 
        user_eligible_for_trial TEXT, 
        user_has_payment_method TEXT, 
        PRIMARY KEY (user_id, list_id), 
        FOREIGN KEY(list_id) REFERENCES lists (list_id), 
        FOREIGN KEY(user_id) REFERENCES lists (user_id)
)

/*
3 rows from lists_users table:
user_id list_id list_update_date_utc    list_creation_date_utc  user_trialist   user_subscriber user_avatar_image_url   user_cover_image_url    user_eligible_for_trial       user_has_payment_method
85981819        1969    2019-11-26      2009-12-18      1       1       https://assets.mubicdn.net/images/avatars/74983/images-w150.jpg?1523895214      None    0    1
85981819        3946    2020-05-01      2010-01-30      1       1       https://assets.mubicdn.net/images/avatars/74983/images-w150.jpg?1523895214      None    0    1
85981819        6683    2020-04-12      2010-03-31      1       1       https://assets.mubicdn.net/images/avatars/74983/images-w150.jpg?1523895214      None    0    1
*/

CREATE TABLE movies (
        movie_id INTEGER NOT NULL, 
        movie_title TEXT, 
        movie_release_year INTEGER, 
        movie_url TEXT, 
        movie_title_language TEXT, 
        movie_popularity INTEGER, 
        movie_image_url TEXT, 
        director_id TEXT, 
        director_name TEXT, 
        director_url TEXT, 
        PRIMARY KEY (movie_id)
)

/*
3 rows from movies table:
movie_id        movie_title     movie_release_year      movie_url       movie_title_language    movie_popularity        movie_image_url director_id     director_namedirector_url
1       La Antena       2007    http://mubi.com/films/la-antena en      105     https://images.mubicdn.net/images/film/1/cache-7927-1581389497/image-w1280.jpg  131  Esteban Sapir    http://mubi.com/cast/esteban-sapir
2       Elementary Particles    2006    http://mubi.com/films/elementary-particles      en      23      https://images.mubicdn.net/images/film/2/cache-512179-1581389841/image-w1280.jpg      73      Oskar Roehler   http://mubi.com/cast/oskar-roehler
3       It's Winter     2006    http://mubi.com/films/its-winter        en      21      https://images.mubicdn.net/images/film/3/cache-7929-1481539519/image-w1280.jpg82      Rafi Pitts      http://mubi.com/cast/rafi-pitts
*/

CREATE TABLE ratings (
        movie_id INTEGER, 
        rating_id INTEGER, 
        rating_url TEXT, 
        rating_score INTEGER, 
        rating_timestamp_utc TEXT, 
        critic TEXT, 
        critic_likes INTEGER, 
        critic_comments INTEGER, 
        user_id INTEGER, 
        user_trialist INTEGER, 
        user_subscriber INTEGER, 
        user_eligible_for_trial INTEGER, 
        user_has_payment_method INTEGER, 
        FOREIGN KEY(movie_id) REFERENCES movies (movie_id), 
        FOREIGN KEY(user_id) REFERENCES lists_users (user_id), 
        FOREIGN KEY(rating_id) REFERENCES ratings (rating_id), 
        FOREIGN KEY(user_id) REFERENCES ratings_users (user_id)
)

/*
3 rows from ratings table:
movie_id        rating_id       rating_url      rating_score    rating_timestamp_utc    critic  critic_likes    critic_comments user_id user_trialist   user_subscriber       user_eligible_for_trial user_has_payment_method
1066    15610495        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/15610495 3       2017-06-10 12:38:33     None    0       0       41579158     00       1       0
1066    10704606        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10704606 2       2014-08-15 23:42:31     None    0       0       85981819     11       0       1
1066    10177114        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10177114 2       2014-01-30 13:21:57     None    0       0       4208563 0    01       1
*/

#
Q: What is the list ID that was first created by user 85981819?
schema_links: [lists_users.list_id, lists_users.user_id, lists_user.list_creation_date_utc, 85981819]
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let’s think step by step. The SQL query for the given question needs these tables = [lists_users], so we don't need JOIN.
Plus, it doesn't require nested queries, and we need the answer to the sub-questions = [""].
So, we don't need JOIN and don't need nested queries, then the SQL query can be classified as "EASY".",
"Label": "EASY",
"sub-questions": [""]}}

Q: How many more movie lists were created by the user who created the movie list \"250 Favourite Films\"?
schema_links: [lists_users.list_id,lists_users.user_id,lists.user_id,lists.list_title,250 Favourite Films]
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let’s think step by step. The SQL query for the given question needs these tables = [lists,lists_users], so we need JOIN.
Plus, it requires nested queries, and we need the answer to the sub-questions = [who created the movie list \"250 Favourite Films\"?].
So, we need JOIN and need nested queries, then the SQL query can be classified as "NESTED".",
"Label": "NESTED",
"sub-questions": [who created the movie list \"250 Favourite Films\"?]}}

Q: What is the percentage of the ratings were rated by user who was a subcriber?
schema_links: [ratings.user_subscriber,1]
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let’s think step by step. The SQL query for the given question needs these tables = [ratings], so we don't need JOIN.
Plus, it doesn't require nested queries, and we need the answer to the sub-questions = [""].
So, we don't need JOIN and don't need nested queries, then the SQL query can be classified as "EASY".",
"Label": "EASY",
"sub-questions": [""]}}

Q: Was the user who created the \"World War 2 and Kids\" list eligible for trial when he created the list? Indicate how many followers does the said list has.
schema_links: [lists_users.user_eligible_for_trial, lists.list_followers, lists.list_title, lists.user_id = lists_user.user_id,lists.list_id = lists_user.list_id, World War 2 and Kids]
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let’s think step by step. The SQL query for the given question needs these tables = [lists, lists_users], so we need JOIN.
Plus, it doesn't need nested queries, and we need the answer to the sub-questions = [""].
So, we need JOIN and don't need nested queries, then the SQL query can be classified as "NON-NESTED".",
"Label": "NON-NESTED",
"sub-questions": [""]}}

Q: Which year was the third movie directed by Quentin Tarantino released? Indicate the user ids of the user who gave it a rating score of 4.
schema_links: [movies.movie_release_year,ratings.user_id,ratings.rating_score,movies.movie_id = ratings.movie_id, movies.director_name, Quentin Tarantino, 4]
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let’s think step by step. The SQL query for the given question needs these tables = [ratings,movies], so we need JOIN.
Plus, it requires nested queries, and we need the answer to the sub-questions = [Which movie is the third movie directed by Quentin Tarantino?].
So, we need JOIN and need nested queries, then the SQL query can be classified as "NESTED".",
"Label": "NESTED",
"sub-questions": [Which movie is the third movie directed by Quentin Tarantino?]}}

Q: What is the average number of followers of the lists created by the user who rated the movie \"Pavee Lackeen: The Traveller Girl\" on 3/27/2011 at 2:06:34 AM?
schema_links: [ratings.rating_timestamp_utc,lists_users.list_id,movies.movie_title,lists.list_followers,ratings.user_id = list_user.user_id,ratings.movie_id = movies.movie_id,lists_users.list_id = lists.list_id,Pavee Lackeen: The Traveller Girl,2011-03-27 02:06:34]
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let’s think step by step. The SQL query for the given question needs these tables = [lists, lists_users,ratings,movies], so we need JOIN.
Plus, it doesn't need nested queries, and we need the answer to the sub-questions = [""].
So, we need JOIN and don't need nested queries, then the SQL query can be classified as "NON-NESTED".",
"Label": "NON-NESTED",
"sub-questions": [""]}}

"""  # noqa: E501
HUMAN_CLASSIFICATION_TEMPLATE = """
For the given question, classify it as EASY, NON-NESTED, or NESTED based on nested queries and JOIN.
if need nested queries: predict NESTED
elif need JOIN and don't need nested queries: predict NON-NESTED
elif don't need JOIN and don't need nested queries: predict EASY
###
Schema of the database with sample rows and column descriptions:
#
{schema}

#
Q: {question}
Schema links: {schema_links}
{history_block}{paths_block}A: Let’s think step by step."""  # noqa: E501

SYSTEM_EASY_CLASS_TEMPLATE = """
Use the schema links to generate the correct sqlite SQL query for the given question.
Hint helps you to write the correct sqlite SQL query.
###
Few examples of this task are:
###
Schema of the database with sample rows and column descriptions:
#
CREATE TABLE lists (
        user_id INTEGER, 
        list_id INTEGER NOT NULL, 
        list_title TEXT, 
        list_movie_number INTEGER, 
        list_update_timestamp_utc TEXT, 
        list_creation_timestamp_utc TEXT, 
        list_followers INTEGER, 
        list_url TEXT, 
        list_comments INTEGER, 
        list_description TEXT, 
        list_cover_image_url TEXT, 
        list_first_image_url TEXT, 
        list_second_image_url TEXT, 
        list_third_image_url TEXT, 
        PRIMARY KEY (list_id), 
        FOREIGN KEY(user_id) REFERENCES lists_users (user_id)
)

/*
3 rows from lists table:
user_id list_id list_title      list_movie_number       list_update_timestamp_utc       list_creation_timestamp_utc     list_followers  list_url        list_commentslist_description list_cover_image_url    list_first_image_url    list_second_image_url   list_third_image_url
88260493        1       Films that made your kid sister cry     5       2019-01-24 19:16:18     2009-11-11 00:02:21     5       http://mubi.com/lists/films-that-made-your-kid-sister-cry     3       <p>Don’t be such a baby!!</p>
<p><strong>bold</strong></p>    https://assets.mubicdn.net/images/film/3822/image-w1280.jpg?1445914994  https://assets.mubicdn.net/images/film/3822/image-w320.jpg?1445914994 https://assets.mubicdn.net/images/film/506/image-w320.jpg?1543838422    https://assets.mubicdn.net/images/film/485/image-w320.jpg?1575331204
45204418        2       Headscratchers  3       2018-12-03 15:12:20     2009-11-11 00:05:11     1       http://mubi.com/lists/headscratchers    2       <p>Films that need at least two viewings to really make sense.</p>
<p>Or at least… they did for <em>       https://assets.mubicdn.net/images/film/4343/image-w1280.jpg?1583331932  https://assets.mubicdn.net/images/film/4343/image-w320.jpg?1583331932 https://assets.mubicdn.net/images/film/159/image-w320.jpg?1548864573    https://assets.mubicdn.net/images/film/142/image-w320.jpg?1544094102
48905025        3       Sexy Time Movies        7       2019-05-30 03:00:07     2009-11-11 00:20:00     6       http://mubi.com/lists/sexy-time-movies  5       <p>Films that get you in the mood…for love. In development.</p>
<p>Remarks</p>
<p><strong>Enter the    https://assets.mubicdn.net/images/film/3491/image-w1280.jpg?1564112978  https://assets.mubicdn.net/images/film/3491/image-w320.jpg?1564112978https://assets.mubicdn.net/images/film/2377/image-w320.jpg?1564675204    https://assets.mubicdn.net/images/film/2874/image-w320.jpg?1546574412
*/

CREATE TABLE lists_users (
        user_id INTEGER NOT NULL, 
        list_id INTEGER NOT NULL, 
        list_update_date_utc TEXT, 
        list_creation_date_utc TEXT, 
        user_trialist INTEGER, 
        user_subscriber INTEGER, 
        user_avatar_image_url TEXT, 
        user_cover_image_url TEXT, 
        user_eligible_for_trial TEXT, 
        user_has_payment_method TEXT, 
        PRIMARY KEY (user_id, list_id), 
        FOREIGN KEY(list_id) REFERENCES lists (list_id), 
        FOREIGN KEY(user_id) REFERENCES lists (user_id)
)

/*
3 rows from lists_users table:
user_id list_id list_update_date_utc    list_creation_date_utc  user_trialist   user_subscriber user_avatar_image_url   user_cover_image_url    user_eligible_for_trial       user_has_payment_method
85981819        1969    2019-11-26      2009-12-18      1       1       https://assets.mubicdn.net/images/avatars/74983/images-w150.jpg?1523895214      None    0    1
85981819        3946    2020-05-01      2010-01-30      1       1       https://assets.mubicdn.net/images/avatars/74983/images-w150.jpg?1523895214      None    0    1
85981819        6683    2020-04-12      2010-03-31      1       1       https://assets.mubicdn.net/images/avatars/74983/images-w150.jpg?1523895214      None    0    1
*/

CREATE TABLE movies (
        movie_id INTEGER NOT NULL, 
        movie_title TEXT, 
        movie_release_year INTEGER, 
        movie_url TEXT, 
        movie_title_language TEXT, 
        movie_popularity INTEGER, 
        movie_image_url TEXT, 
        director_id TEXT, 
        director_name TEXT, 
        director_url TEXT, 
        PRIMARY KEY (movie_id)
)

/*
3 rows from movies table:
movie_id        movie_title     movie_release_year      movie_url       movie_title_language    movie_popularity        movie_image_url director_id     director_namedirector_url
1       La Antena       2007    http://mubi.com/films/la-antena en      105     https://images.mubicdn.net/images/film/1/cache-7927-1581389497/image-w1280.jpg  131  Esteban Sapir    http://mubi.com/cast/esteban-sapir
2       Elementary Particles    2006    http://mubi.com/films/elementary-particles      en      23      https://images.mubicdn.net/images/film/2/cache-512179-1581389841/image-w1280.jpg      73      Oskar Roehler   http://mubi.com/cast/oskar-roehler
3       It's Winter     2006    http://mubi.com/films/its-winter        en      21      https://images.mubicdn.net/images/film/3/cache-7929-1481539519/image-w1280.jpg82      Rafi Pitts      http://mubi.com/cast/rafi-pitts
*/

CREATE TABLE ratings (
        movie_id INTEGER, 
        rating_id INTEGER, 
        rating_url TEXT, 
        rating_score INTEGER, 
        rating_timestamp_utc TEXT, 
        critic TEXT, 
        critic_likes INTEGER, 
        critic_comments INTEGER, 
        user_id INTEGER, 
        user_trialist INTEGER, 
        user_subscriber INTEGER, 
        user_eligible_for_trial INTEGER, 
        user_has_payment_method INTEGER, 
        FOREIGN KEY(movie_id) REFERENCES movies (movie_id), 
        FOREIGN KEY(user_id) REFERENCES lists_users (user_id), 
        FOREIGN KEY(rating_id) REFERENCES ratings (rating_id), 
        FOREIGN KEY(user_id) REFERENCES ratings_users (user_id)
)

/*
3 rows from ratings table:
movie_id        rating_id       rating_url      rating_score    rating_timestamp_utc    critic  critic_likes    critic_comments user_id user_trialist   user_subscriber       user_eligible_for_trial user_has_payment_method
1066    15610495        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/15610495 3       2017-06-10 12:38:33     None    0       0       41579158     00       1       0
1066    10704606        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10704606 2       2014-08-15 23:42:31     None    0       0       85981819     11       0       1
1066    10177114        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10177114 2       2014-01-30 13:21:57     None    0       0       4208563 0    01       1
*/
#
Q: What is the name of the longest movie title? When was it released?
Schema_links: [movies.movie_title,movies.movie_release_year, movies.movie_popularity]
Please respond with a JSON object structured as follows:
{{"SQL": "SELECT movie_title, movie_release_year FROM movies ORDER BY LENGTH(movie_popularity) DESC LIMIT 1"}}

Q: What is the percentage of the ratings were rated by user who was a subcriber?
Schema_links: [ratings.user_subscriber,1]
Please respond with a JSON object structured as follows:
{{"SQL": "SELECT CAST(SUM(CASE WHEN user_subscriber = 1 THEN 1 ELSE 0 END) AS REAL) * 100 / COUNT(*) FROM ratings"}}

Q: When was the first movie released and who directed it?
Schema_links: [movies.movie_release_year, movies.director_name]
Please respond with a JSON object structured as follows:
{{"SQL": "SELECT movie_release_year, director_name FROM movies WHERE movie_release_year IS NOT NULL ORDER BY movie_release_year ASC LIMIT 1"}}

Q: How many movie lists were still updated 10 years after it was created?
Schema_links: [lists.list_update_timestamp_utc, lists.list_creation_timestamp_utc, 10]
Please respond with a JSON object structured as follows:
{{"SQL": "SELECT COUNT(*) FROM lists WHERE SUBSTR(list_update_timestamp_utc, 1, 4) - SUBSTR(list_creation_timestamp_utc, 1, 4) > 10"}}

Q: For the list with more than 200 followers, state the title and how long the list has been created?
Schema_links: [lists.list_title, lists.list_update_timestamp_utc,lists.list_followers, 200]
Please respond with a JSON object structured as follows:
{{"SQL": "SELECT list_title , 365 * (strftime('%Y', 'now') - strftime('%Y', list_creation_timestamp_utc)) + 30 * (strftime('%m', 'now') - strftime('%m', list_creation_timestamp_utc)) + strftime('%d', 'now') - strftime('%d', list_creation_timestamp_utc) FROM lists WHERE list_followers > 200"}}

Q: What is the percentage of list created by user who was a subscriber when he created the list?
Schema_links: [lists_users.user_subscriber,1]
Please respond with a JSON object structured as follows:
{{"SQL": "SELECT CAST(SUM(CASE WHEN user_subscriber = 1 THEN 1 ELSE 0 END) AS REAL) * 100 / COUNT(list_id) FROM lists_users"}}
"""  # noqa: E501
HUMAN_EASY_CLASS_TEMPLATE = """
Use the schema links to generate the correct sqlite SQL query for the given question.
###
Schema of the database with sample rows and column descriptions:
#
{schema}

#
Q: {question}
Schema_links: {schema_links}
{history_block}{paths_block}SQL: """

SYSTEM_NON_NESTED_CLASS_TEMPLATE = """
Use the the schema links and intermediate reasoning steps to generate the correct sqlite SQL query for the given question.
Hint helps you to write the correct sqlite SQL query.
###
Few examples of this task are:
###
Schema of the database with sample rows and column descriptions:
#
CREATE TABLE ratings (
        movie_id INTEGER, 
        rating_id INTEGER, 
        rating_url TEXT, 
        rating_score INTEGER, 
        rating_timestamp_utc TEXT, 
        critic TEXT, 
        critic_likes INTEGER, 
        critic_comments INTEGER, 
        user_id INTEGER, 
        user_trialist INTEGER, 
        user_subscriber INTEGER, 
        user_eligible_for_trial INTEGER, 
        user_has_payment_method INTEGER, 
        FOREIGN KEY(movie_id) REFERENCES movies (movie_id), 
        FOREIGN KEY(user_id) REFERENCES lists_users (user_id), 
        FOREIGN KEY(rating_id) REFERENCES ratings (rating_id), 
        FOREIGN KEY(user_id) REFERENCES ratings_users (user_id)
)

/*
3 rows from ratings table:
movie_id        rating_id       rating_url      rating_score    rating_timestamp_utc    critic  critic_likes    critic_comments user_id user_trialist   user_subscriber       user_eligible_for_trial user_has_payment_method
1066    15610495        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/15610495 3       2017-06-10 12:38:33     None    0       0       41579158     00       1       0
1066    10704606        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10704606 2       2014-08-15 23:42:31     None    0       0       85981819     11       0       1
1066    10177114        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10177114 2       2014-01-30 13:21:57     None    0       0       4208563 0    01       1
*/

CREATE TABLE movies (
        movie_id INTEGER NOT NULL, 
        movie_title TEXT, 
        movie_release_year INTEGER, 
        movie_url TEXT, 
        movie_title_language TEXT, 
        movie_popularity INTEGER, 
        movie_image_url TEXT, 
        director_id TEXT, 
        director_name TEXT, 
        director_url TEXT, 
        PRIMARY KEY (movie_id)
)

/*
3 rows from movies table:
movie_id        movie_title     movie_release_year      movie_url       movie_title_language    movie_popularity        movie_image_url director_id     director_namedirector_url
1       La Antena       2007    http://mubi.com/films/la-antena en      105     https://images.mubicdn.net/images/film/1/cache-7927-1581389497/image-w1280.jpg  131  Esteban Sapir    http://mubi.com/cast/esteban-sapir
2       Elementary Particles    2006    http://mubi.com/films/elementary-particles      en      23      https://images.mubicdn.net/images/film/2/cache-512179-1581389841/image-w1280.jpg      73      Oskar Roehler   http://mubi.com/cast/oskar-roehler
3       It's Winter     2006    http://mubi.com/films/its-winter        en      21      https://images.mubicdn.net/images/film/3/cache-7929-1481539519/image-w1280.jpg82      Rafi Pitts      http://mubi.com/cast/rafi-pitts
*/
#
Q: What is the average rating for movie titled 'When Will I Be Loved'?
Schema_links: [ratings.rating_score, movies.movie_title, movies.movie_id = ratings.movie_id, When Will I Be Loved]
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let’s think step by step. For creating the SQL for the given question, we need to join these tables = [ratings,movies].
First of all, for joining these tables we have to use the common column = [ratings.movie_id = movies.movie_id].
Now, we have to filter the rows where movie_title = 'When Will I Be Loved'.
Then, we have to find the average of the rating_score.",
"SQL": "SELECT AVG(T2.rating_score) FROM movies AS T1 INNER JOIN ratings AS T2 ON T1.movie_id = T2.movie_id WHERE T1.movie_title = 'When Will I Be Loved'"}}

Q: For movie titled 'Welcome to the Dollhouse', how many percentage of the ratings were rated with highest score.
Schema_links: [ratings.rating_score, movies.movie_title, movies.movie_id = ratings.movie_id, Welcome to the Dollhouse]
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let’s think step by step. For creating the SQL for the given question, we need to join these tables = [ratings,movies].
First of all, for joining these tables we have to use the common column = [ratings.movie_id = movies.movie_id].
Now, we have to filter the rows where movie_title = 'Welcome to the Dollhouse'.
Then, we have to find the percentage of the ratings were rated with highest score which is 5.",
"SQL": "SELECT CAST(SUM(CASE WHEN T2.rating_score = 5 THEN 1 ELSE 0 END) AS REAL) * 100 / COUNT(*) FROM movies AS T1 INNER JOIN ratings AS T2 ON T1.movie_id = T2.movie_id WHERE T1.movie_title = 'Welcome to the Dollhouse'"}}

Q: For all ratings which are rated in year 2020, name the movies which has the rating scored 4 and above.
Schema_links: [ratings.rating_timestamp_utc, movies.movie_title, movies.movie_id = ratings.movie_id, 2020, 4]
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let’s think step by step. For creating the SQL for the given question, we need to join these tables = [ratings,movies].
First of all, for joining these tables we have to use the common column = [ratings.movie_id = movies.movie_id].
Now, we have to filter the rows where rating_timestamp_utc like '%2020%' and rating_score > = 4.
Then, we have to find the movie_title.",
"SQL": "SELECT T2.movie_title FROM ratings AS T1 INNER JOIN movies AS T2 ON T1.movie_id = T2.movie_id WHERE CAST(SUBSTR(T1.rating_timestamp_utc, 1, 4) AS INTEGER) = 2020 AND CAST(SUBSTR(T1.rating_timestamp_utc, 6, 2) AS INTEGER) > 4"}}

Q: What is the average score of the movie \"The Fall of Berlin\" in 2019?
Schema_links: [ratings.rating_score, ratings.rating_id, movies.movie_title, T1.rating_timestamp_utc, movies.movie_id = ratings.movie_id, The Fall of Berlin, 2019]
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let’s think step by step. For creating the SQL for the given question, we need to join these tables = [ratings,movies].
First of all, for joining these tables we have to use the common column = [ratings.movie_id = movies.movie_id].
Now, we have to filter the rows where movie_title = 'The Fall of Berlin' and rating_timestamp_utc = 2019.
Then, we have to find the average of the rating_score which can be computed by dividing the sum of rating_score by the count of rating_id.",
"SQL": "SELECT SUM(T1.rating_score) / COUNT(T1.rating_id) FROM ratings AS T1 INNER JOIN movies AS T2 ON T1.movie_id = T2.movie_id WHERE T1.rating_timestamp_utc LIKE '2019%' AND T2.movie_title LIKE 'The Fall of Berlin'"}}
"""  # noqa: E501
SYSTEM_NON_NESTED_CLASS_TEMPLATE_JOIN = """
Use the the schema links and intermediate reasoning steps to generate the correct sqlite SQL query for the given question.
Hint helps you to write the correct sqlite SQL query.
###
Few examples of this task are:
###
Schema of the database with sample rows and column descriptions:
#
CREATE TABLE ratings (
        movie_id INTEGER, 
        rating_id INTEGER, 
        rating_url TEXT, 
        rating_score INTEGER, 
        rating_timestamp_utc TEXT, 
        critic TEXT, 
        critic_likes INTEGER, 
        critic_comments INTEGER, 
        user_id INTEGER, 
        user_trialist INTEGER, 
        user_subscriber INTEGER, 
        user_eligible_for_trial INTEGER, 
        user_has_payment_method INTEGER, 
        FOREIGN KEY(movie_id) REFERENCES movies (movie_id), 
        FOREIGN KEY(user_id) REFERENCES lists_users (user_id), 
        FOREIGN KEY(rating_id) REFERENCES ratings (rating_id), 
        FOREIGN KEY(user_id) REFERENCES ratings_users (user_id)
)

/*
3 rows from ratings table:
movie_id        rating_id       rating_url      rating_score    rating_timestamp_utc    critic  critic_likes    critic_comments user_id user_trialist   user_subscriber       user_eligible_for_trial user_has_payment_method
1066    15610495        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/15610495 3       2017-06-10 12:38:33     None    0       0       41579158     00       1       0
1066    10704606        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10704606 2       2014-08-15 23:42:31     None    0       0       85981819     11       0       1
1066    10177114        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10177114 2       2014-01-30 13:21:57     None    0       0       4208563 0    01       1
*/

CREATE TABLE movies (
        movie_id INTEGER NOT NULL, 
        movie_title TEXT, 
        movie_release_year INTEGER, 
        movie_url TEXT, 
        movie_title_language TEXT, 
        movie_popularity INTEGER, 
        movie_image_url TEXT, 
        director_id TEXT, 
        director_name TEXT, 
        director_url TEXT, 
        PRIMARY KEY (movie_id)
)

/*
3 rows from movies table:
movie_id        movie_title     movie_release_year      movie_url       movie_title_language    movie_popularity        movie_image_url director_id     director_namedirector_url
1       La Antena       2007    http://mubi.com/films/la-antena en      105     https://images.mubicdn.net/images/film/1/cache-7927-1581389497/image-w1280.jpg  131  Esteban Sapir    http://mubi.com/cast/esteban-sapir
2       Elementary Particles    2006    http://mubi.com/films/elementary-particles      en      23      https://images.mubicdn.net/images/film/2/cache-512179-1581389841/image-w1280.jpg      73      Oskar Roehler   http://mubi.com/cast/oskar-roehler
3       It's Winter     2006    http://mubi.com/films/its-winter        en      21      https://images.mubicdn.net/images/film/3/cache-7929-1481539519/image-w1280.jpg82      Rafi Pitts      http://mubi.com/cast/rafi-pitts
*/

CREATE TABLE movies_join_ratings (
    movies_movie_id INTEGER,
    movie_title TEXT,
    movie_release_year INTEGER,
    movie_url TEXT,
    movie_title_language TEXT,
    movie_popularity INTEGER,
    movie_image_url TEXT,
    director_id TEXT,
    director_name TEXT,
    director_url TEXT,
    ratings_movie_id INTEGER,
    rating_id INTEGER,
    rating_url TEXT,
    rating_score INTEGER,
    rating_timestamp_utc TEXT,
    critic TEXT,
    critic_likes INTEGER,
    critic_comments INTEGER,
    user_id INTEGER,
    user_trialist INTEGER,
    user_subscriber INTEGER,
    user_eligible_for_trial INTEGER,
    user_has_payment_method INTEGER
)
/*
3 rows from movies_join_ratings table:
movies_movie_id	movie_title	movie_release_year	movie_url	movie_title_language	movie_popularity	movie_image_url	director_id	director_name	director_url	ratings_movie_id	rating_id	rating_url	rating_score	rating_timestamp_utc	critic	critic_likes	critic_comments	user_id	user_trialist	user_subscriber	user_eligible_for_trial	user_has_payment_method
1066	Pavee Lackeen: The Traveller Girl	2005	http://mubi.com/films/pavee-lackeen-the-traveller-girl	en	1	https://images.mubicdn.net/images/film/1066/cache-8564-1481540828/image-w1280.jpg	11337	Perry Ogden	http://mubi.com/cast/perry-ogden	1066	15610495	http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/15610495	3	2017-06-10 12:38:33	None	0	0	41579158	0	0	1	0
1066	Pavee Lackeen: The Traveller Girl	2005	http://mubi.com/films/pavee-lackeen-the-traveller-girl	en	1	https://images.mubicdn.net/images/film/1066/cache-8564-1481540828/image-w1280.jpg	11337	Perry Ogden	http://mubi.com/cast/perry-ogden	1066	10704606	http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10704606	2	2014-08-15 23:42:31	None	0	0	85981819	1	1	0	1
1066	Pavee Lackeen: The Traveller Girl	2005	http://mubi.com/films/pavee-lackeen-the-traveller-girl	en	1	https://images.mubicdn.net/images/film/1066/cache-8564-1481540828/image-w1280.jpg	11337	Perry Ogden	http://mubi.com/cast/perry-ogden	1066	10177114	http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10177114	2	2014-01-30 13:21:57	None	0	0	4208563	0	0	1	1
*/
#
Q: What is the average rating for movie titled 'When Will I Be Loved'?
Schema_links: [ratings.rating_score, movies.movie_title, movies.movie_id = ratings.movie_id, When Will I Be Loved]
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let’s think step by step. For creating the SQL for the given question, we need to join these tables = [ratings,movies].
First of all, for joining these tables we have to use the common column = [ratings.movie_id = movies.movie_id].
There is a join result table that is named movies_join_ratings which already has the join of these two tables, so we can use this table directly.
Now, we have to filter the rows where movie_title = 'When Will I Be Loved'.
Then, we have to find the average of the rating_score.",
"SQL": "SELECT AVG(rating_score) FROM movies_join_ratings WHERE movie_title = 'When Will I Be Loved'"}}

Q: For movie titled 'Welcome to the Dollhouse', how many percentage of the ratings were rated with highest score.
Schema_links: [ratings.rating_score, movies.movie_title, movies.movie_id = ratings.movie_id, Welcome to the Dollhouse]
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let’s think step by step. For creating the SQL for the given question, we need to join these tables = [ratings,movies].
First of all, for joining these tables we have to use the common column = [ratings.movie_id = movies.movie_id].
There is a join result table that is named movies_join_ratings which already has the join of these two tables, so we can use this table directly.
Now, we have to filter the rows where movie_title = 'Welcome to the Dollhouse'.
Then, we have to find the percentage of the ratings were rated with highest score which is 5.",
"SQL": "SELECT CAST(SUM(CASE WHEN rating_score = 5 THEN 1 ELSE 0 END) AS REAL) * 100 / COUNT(*) FROM movies_join_ratings WHERE movie_title = 'Welcome to the Dollhouse'"}}

Q: For all ratings which are rated in year 2020, name the movies which has the rating scored 4 and above.
Schema_links: [ratings.rating_timestamp_utc, movies.movie_title, movies.movie_id = ratings.movie_id, 2020, 4]
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let’s think step by step. For creating the SQL for the given question, we need to join these tables = [ratings,movies].
First of all, for joining these tables we have to use the common column = [ratings.movie_id = movies.movie_id].
There is a join result table that is named movies_join_ratings which already has the join of these two tables, so we can use this table directly.
Now, we have to filter the rows where rating_timestamp_utc like '%2020%' and rating_score > = 4.
Then, we have to find the movie_title.",
"SQL": "SELECT movie_title FROM movies_join_ratings WHERE CAST(SUBSTR(rating_timestamp_utc, 1, 4) AS INTEGER) = 2020 AND CAST(SUBSTR(rating_timestamp_utc, 6, 2) AS INTEGER) > 4"}}

Q: What is the average score of the movie \"The Fall of Berlin\" in 2019?
Schema_links: [ratings.rating_score, ratings.rating_id, movies.movie_title, T1.rating_timestamp_utc, movies.movie_id = ratings.movie_id, The Fall of Berlin, 2019]
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let’s think step by step. For creating the SQL for the given question, we need to join these tables = [ratings,movies].
First of all, for joining these tables we have to use the common column = [ratings.movie_id = movies.movie_id].
There is a join result table that is named movies_join_ratings which already has the join of these two tables, so we can use this table directly.
Now, we have to filter the rows where movie_title = 'The Fall of Berlin' and rating_timestamp_utc = 2019.
Then, we have to find the average of the rating_score which can be computed by dividing the sum of rating_score by the count of rating_id.",
"SQL": "SELECT SUM(rating_score) / COUNT(rating_id) FROM movies_join_ratings WHERE rating_timestamp_utc LIKE '2019%' AND movie_title LIKE 'The Fall of Berlin'"}}
"""  # noqa: E501
SYSTEM_NON_NESTED_CLASS_TEMPLATE_JOIN_VIEW = """
Use the the schema links and intermediate reasoning steps to generate the correct sqlite SQL query for the given question.
Hint helps you to write the correct sqlite SQL query.
###
Few examples of this task are:
###
Schema of the database with sample rows and column descriptions:
#
CREATE TABLE ratings (
        movie_id INTEGER, 
        rating_id INTEGER, 
        rating_url TEXT, 
        rating_score INTEGER, 
        rating_timestamp_utc TEXT, 
        critic TEXT, 
        critic_likes INTEGER, 
        critic_comments INTEGER, 
        user_id INTEGER, 
        user_trialist INTEGER, 
        user_subscriber INTEGER, 
        user_eligible_for_trial INTEGER, 
        user_has_payment_method INTEGER, 
        FOREIGN KEY(movie_id) REFERENCES movies (movie_id), 
        FOREIGN KEY(user_id) REFERENCES lists_users (user_id), 
        FOREIGN KEY(rating_id) REFERENCES ratings (rating_id), 
        FOREIGN KEY(user_id) REFERENCES ratings_users (user_id)
)

/*
3 rows from ratings table:
movie_id        rating_id       rating_url      rating_score    rating_timestamp_utc    critic  critic_likes    critic_comments user_id user_trialist   user_subscriber       user_eligible_for_trial user_has_payment_method
1066    15610495        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/15610495 3       2017-06-10 12:38:33     None    0       0       41579158     00       1       0
1066    10704606        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10704606 2       2014-08-15 23:42:31     None    0       0       85981819     11       0       1
1066    10177114        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10177114 2       2014-01-30 13:21:57     None    0       0       4208563 0    01       1
*/

CREATE TABLE movies (
        movie_id INTEGER NOT NULL, 
        movie_title TEXT, 
        movie_release_year INTEGER, 
        movie_url TEXT, 
        movie_title_language TEXT, 
        movie_popularity INTEGER, 
        movie_image_url TEXT, 
        director_id TEXT, 
        director_name TEXT, 
        director_url TEXT, 
        PRIMARY KEY (movie_id)
)

/*
3 rows from movies table:
movie_id        movie_title     movie_release_year      movie_url       movie_title_language    movie_popularity        movie_image_url director_id     director_namedirector_url
1       La Antena       2007    http://mubi.com/films/la-antena en      105     https://images.mubicdn.net/images/film/1/cache-7927-1581389497/image-w1280.jpg  131  Esteban Sapir    http://mubi.com/cast/esteban-sapir
2       Elementary Particles    2006    http://mubi.com/films/elementary-particles      en      23      https://images.mubicdn.net/images/film/2/cache-512179-1581389841/image-w1280.jpg      73      Oskar Roehler   http://mubi.com/cast/oskar-roehler
3       It's Winter     2006    http://mubi.com/films/its-winter        en      21      https://images.mubicdn.net/images/film/3/cache-7929-1481539519/image-w1280.jpg82      Rafi Pitts      http://mubi.com/cast/rafi-pitts
*/

CREATE VIEW `movies_join_ratings` AS
SELECT
  `movies`.`movie_id` AS `movies_movie_id`,
  `movies`.`movie_title`,
  `movies`.`movie_release_year`,
  `movies`.`movie_url`,
  `movies`.`movie_title_language`,
  `movies`.`movie_popularity`,
  `movies`.`movie_image_url`,
  `movies`.`director_id`,
  `movies`.`director_name`,
  `movies`.`director_url`,
  `ratings`.`movie_id` AS `ratings_movie_id`,
  `ratings`.`rating_id`,
  `ratings`.`rating_url`,
  `ratings`.`rating_score`,
  `ratings`.`rating_timestamp_utc`,
  `ratings`.`critic`,
  `ratings`.`critic_likes`,
  `ratings`.`critic_comments`,
  `ratings`.`user_id`,
  `ratings`.`user_trialist`,
  `ratings`.`user_subscriber`,
  `ratings`.`user_eligible_for_trial`,
  `ratings`.`user_has_payment_method`
FROM `movies`
JOIN `ratings` ON `ratings`.`movie_id` = `movies`.`movie_id` 

 /* 3 rows from movies_join_ratings: 
 movies_movie_id                movie_title movie_release_year                                      movie_url movie_title_language movie_popularity                                           movie_image_url director_id director_name                     director_url ratings_movie_id rating_id                                            rating_url rating_score rating_timestamp_utc critic critic_likes critic_comments  user_id user_trialist user_subscriber user_eligible_for_trial user_has_payment_method 
1066 Pavee Lackeen: The Traveller Girl                       2005 http://mubi.com/films/pavee-lackeen-the-traveller-girl                          en                                    1 https://images.mubicdn.net/images/film/1066/cache-8564-1481540828/image-w1280.jpg               11337           Perry Ogden http://mubi.com/cast/perry-ogden             1066          15610495 http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/15610495                    3           2017-06-10 12:38:33   None            0               0 41579158             0               0                       1                       0 
1066 Pavee Lackeen: The Traveller Girl                       2005 http://mubi.com/films/pavee-lackeen-the-traveller-girl                          en                                    1 https://images.mubicdn.net/images/film/1066/cache-8564-1481540828/image-w1280.jpg               11337           Perry Ogden http://mubi.com/cast/perry-ogden             1066          10704606 http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10704606                    2           2014-08-15 23:42:31   None            0               0 85981819             1               1                       0                       1 
1066 Pavee Lackeen: The Traveller Girl                       2005 http://mubi.com/films/pavee-lackeen-the-traveller-girl                          en                                    1 https://images.mubicdn.net/images/film/1066/cache-8564-1481540828/image-w1280.jpg               11337           Perry Ogden http://mubi.com/cast/perry-ogden             1066          10177114 http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10177114                    2           2014-01-30 13:21:57   None            0               0  4208563             0               0                       1                       1  
 */
#
Q: What is the average rating for movie titled 'When Will I Be Loved'?
Schema_links: [ratings.rating_score, movies.movie_title, movies.movie_id = ratings.movie_id, When Will I Be Loved]
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let’s think step by step. For creating the SQL for the given question, we need to join these tables = [ratings,movies].
First of all, for joining these tables we have to use the common column = [ratings.movie_id = movies.movie_id].
There is a join result table that is named movies_join_ratings which already has the join of these two tables, so we can use this table directly.
Now, we have to filter the rows where movie_title = 'When Will I Be Loved'.
Then, we have to find the average of the rating_score.",
"SQL": "SELECT AVG(rating_score) FROM movies_join_ratings WHERE movie_title = 'When Will I Be Loved'"}}

Q: For movie titled 'Welcome to the Dollhouse', how many percentage of the ratings were rated with highest score.
Schema_links: [ratings.rating_score, movies.movie_title, movies.movie_id = ratings.movie_id, Welcome to the Dollhouse]
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let’s think step by step. For creating the SQL for the given question, we need to join these tables = [ratings,movies].
First of all, for joining these tables we have to use the common column = [ratings.movie_id = movies.movie_id].
There is a join result table that is named movies_join_ratings which already has the join of these two tables, so we can use this table directly.
Now, we have to filter the rows where movie_title = 'Welcome to the Dollhouse'.
Then, we have to find the percentage of the ratings were rated with highest score which is 5.",
"SQL": "SELECT CAST(SUM(CASE WHEN rating_score = 5 THEN 1 ELSE 0 END) AS REAL) * 100 / COUNT(*) FROM movies_join_ratings WHERE movie_title = 'Welcome to the Dollhouse'"}}

Q: For all ratings which are rated in year 2020, name the movies which has the rating scored 4 and above.
Schema_links: [ratings.rating_timestamp_utc, movies.movie_title, movies.movie_id = ratings.movie_id, 2020, 4]
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let’s think step by step. For creating the SQL for the given question, we need to join these tables = [ratings,movies].
First of all, for joining these tables we have to use the common column = [ratings.movie_id = movies.movie_id].
There is a join result table that is named movies_join_ratings which already has the join of these two tables, so we can use this table directly.
Now, we have to filter the rows where rating_timestamp_utc like '%2020%' and rating_score > = 4.
Then, we have to find the movie_title.",
"SQL": "SELECT movie_title FROM movies_join_ratings WHERE CAST(SUBSTR(rating_timestamp_utc, 1, 4) AS INTEGER) = 2020 AND CAST(SUBSTR(rating_timestamp_utc, 6, 2) AS INTEGER) > 4"}}

Q: What is the average score of the movie \"The Fall of Berlin\" in 2019?
Schema_links: [ratings.rating_score, ratings.rating_id, movies.movie_title, T1.rating_timestamp_utc, movies.movie_id = ratings.movie_id, The Fall of Berlin, 2019]
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let’s think step by step. For creating the SQL for the given question, we need to join these tables = [ratings,movies].
First of all, for joining these tables we have to use the common column = [ratings.movie_id = movies.movie_id].
There is a join result table that is named movies_join_ratings which already has the join of these two tables, so we can use this table directly.
Now, we have to filter the rows where movie_title = 'The Fall of Berlin' and rating_timestamp_utc = 2019.
Then, we have to find the average of the rating_score which can be computed by dividing the sum of rating_score by the count of rating_id.",
"SQL": "SELECT SUM(rating_score) / COUNT(rating_id) FROM movies_join_ratings WHERE rating_timestamp_utc LIKE '2019%' AND movie_title LIKE 'The Fall of Berlin'"}}
"""  # noqa: E501
HUMAN_NON_NESTED_CLASS_TEMPLATE = """
Use the the schema links and intermediate reasoning steps to generate the correct sqlite SQL query for the given question.
###
Schema of the database with sample rows and column descriptions:
#
{schema}

#
Q: {question}
Schema_links: {schema_links}
{history_block}{paths_block}A: Let’s think step by step. """  # noqa: E501

SYSTEM_NESTED_CLASS_TEMPLATE = """
Use the the schema links and intermediate reasoning steps to generate the correct sqlite SQL query for the given question.
Hint helps you to write the correct sqlite SQL query.
###
Few examples of this task are:
###
Schema of the database with sample rows and column descriptions:
#
CREATE TABLE lists (
        user_id INTEGER, 
        list_id INTEGER NOT NULL, 
        list_title TEXT, 
        list_movie_number INTEGER, 
        list_update_timestamp_utc TEXT, 
        list_creation_timestamp_utc TEXT, 
        list_followers INTEGER, 
        list_url TEXT, 
        list_comments INTEGER, 
        list_description TEXT, 
        list_cover_image_url TEXT, 
        list_first_image_url TEXT, 
        list_second_image_url TEXT, 
        list_third_image_url TEXT, 
        PRIMARY KEY (list_id), 
        FOREIGN KEY(user_id) REFERENCES lists_users (user_id)
)

/*
3 rows from lists table:
user_id list_id list_title      list_movie_number       list_update_timestamp_utc       list_creation_timestamp_utc     list_followers  list_url        list_commentslist_description list_cover_image_url    list_first_image_url    list_second_image_url   list_third_image_url
88260493        1       Films that made your kid sister cry     5       2019-01-24 19:16:18     2009-11-11 00:02:21     5       http://mubi.com/lists/films-that-made-your-kid-sister-cry     3       <p>Don’t be such a baby!!</p>
<p><strong>bold</strong></p>    https://assets.mubicdn.net/images/film/3822/image-w1280.jpg?1445914994  https://assets.mubicdn.net/images/film/3822/image-w320.jpg?1445914994 https://assets.mubicdn.net/images/film/506/image-w320.jpg?1543838422    https://assets.mubicdn.net/images/film/485/image-w320.jpg?1575331204
45204418        2       Headscratchers  3       2018-12-03 15:12:20     2009-11-11 00:05:11     1       http://mubi.com/lists/headscratchers    2       <p>Films that need at least two viewings to really make sense.</p>
<p>Or at least… they did for <em>       https://assets.mubicdn.net/images/film/4343/image-w1280.jpg?1583331932  https://assets.mubicdn.net/images/film/4343/image-w320.jpg?1583331932 https://assets.mubicdn.net/images/film/159/image-w320.jpg?1548864573    https://assets.mubicdn.net/images/film/142/image-w320.jpg?1544094102
48905025        3       Sexy Time Movies        7       2019-05-30 03:00:07     2009-11-11 00:20:00     6       http://mubi.com/lists/sexy-time-movies  5       <p>Films that get you in the mood…for love. In development.</p>
<p>Remarks</p>
<p><strong>Enter the    https://assets.mubicdn.net/images/film/3491/image-w1280.jpg?1564112978  https://assets.mubicdn.net/images/film/3491/image-w320.jpg?1564112978https://assets.mubicdn.net/images/film/2377/image-w320.jpg?1564675204    https://assets.mubicdn.net/images/film/2874/image-w320.jpg?1546574412
*/


CREATE TABLE lists_users (
        user_id INTEGER NOT NULL, 
        list_id INTEGER NOT NULL, 
        list_update_date_utc TEXT, 
        list_creation_date_utc TEXT, 
        user_trialist INTEGER, 
        user_subscriber INTEGER, 
        user_avatar_image_url TEXT, 
        user_cover_image_url TEXT, 
        user_eligible_for_trial TEXT, 
        user_has_payment_method TEXT, 
        PRIMARY KEY (user_id, list_id), 
        FOREIGN KEY(list_id) REFERENCES lists (list_id), 
        FOREIGN KEY(user_id) REFERENCES lists (user_id)
)

/*
3 rows from lists_users table:
user_id list_id list_update_date_utc    list_creation_date_utc  user_trialist   user_subscriber user_avatar_image_url   user_cover_image_url    user_eligible_for_trial       user_has_payment_method
85981819        1969    2019-11-26      2009-12-18      1       1       https://assets.mubicdn.net/images/avatars/74983/images-w150.jpg?1523895214      None    0    1
85981819        3946    2020-05-01      2010-01-30      1       1       https://assets.mubicdn.net/images/avatars/74983/images-w150.jpg?1523895214      None    0    1
85981819        6683    2020-04-12      2010-03-31      1       1       https://assets.mubicdn.net/images/avatars/74983/images-w150.jpg?1523895214      None    0    1
*/

CREATE TABLE ratings (
        movie_id INTEGER, 
        rating_id INTEGER, 
        rating_url TEXT, 
        rating_score INTEGER, 
        rating_timestamp_utc TEXT, 
        critic TEXT, 
        critic_likes INTEGER, 
        critic_comments INTEGER, 
        user_id INTEGER, 
        user_trialist INTEGER, 
        user_subscriber INTEGER, 
        user_eligible_for_trial INTEGER, 
        user_has_payment_method INTEGER, 
        FOREIGN KEY(movie_id) REFERENCES movies (movie_id), 
        FOREIGN KEY(user_id) REFERENCES lists_users (user_id), 
        FOREIGN KEY(rating_id) REFERENCES ratings (rating_id), 
        FOREIGN KEY(user_id) REFERENCES ratings_users (user_id)
)

/*
3 rows from ratings table:
movie_id        rating_id       rating_url      rating_score    rating_timestamp_utc    critic  critic_likes    critic_comments user_id user_trialist   user_subscriber       user_eligible_for_trial user_has_payment_method
1066    15610495        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/15610495 3       2017-06-10 12:38:33     None    0       0       41579158     00       1       0
1066    10704606        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10704606 2       2014-08-15 23:42:31     None    0       0       85981819     11       0       1
1066    10177114        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10177114 2       2014-01-30 13:21:57     None    0       0       4208563 0    01       1
*/

CREATE TABLE movies (
        movie_id INTEGER NOT NULL, 
        movie_title TEXT, 
        movie_release_year INTEGER, 
        movie_url TEXT, 
        movie_title_language TEXT, 
        movie_popularity INTEGER, 
        movie_image_url TEXT, 
        director_id TEXT, 
        director_name TEXT, 
        director_url TEXT, 
        PRIMARY KEY (movie_id)
)

/*
3 rows from movies table:
movie_id        movie_title     movie_release_year      movie_url       movie_title_language    movie_popularity        movie_image_url director_id     director_namedirector_url
1       La Antena       2007    http://mubi.com/films/la-antena en      105     https://images.mubicdn.net/images/film/1/cache-7927-1581389497/image-w1280.jpg  131  Esteban Sapir    http://mubi.com/cast/esteban-sapir
2       Elementary Particles    2006    http://mubi.com/films/elementary-particles      en      23      https://images.mubicdn.net/images/film/2/cache-512179-1581389841/image-w1280.jpg      73      Oskar Roehler   http://mubi.com/cast/oskar-roehler
3       It's Winter     2006    http://mubi.com/films/its-winter        en      21      https://images.mubicdn.net/images/film/3/cache-7929-1481539519/image-w1280.jpg82      Rafi Pitts      http://mubi.com/cast/rafi-pitts
*/

#
Q: How many more movie lists were created by the user who created the movie list \"250 Favourite Films\"?
Schema_links: [lists_users.list_id, lists_users.user_id = lists.user_id, lists.list_title, 250 Favourite Films]
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let's think step by step. the given question can be solved by knowing the answer to the following sub-questions = [which user has created the movie list \"250 Favourite Films\".]
The sqlite SQL query for the sub-question "which user has created the movie list \"250 Favourite Films\"" is SELECT user_id FROM lists WHERE list_title = '250 Favourite Films'
The above query will return the user_id of the user who has created the movie list \"250 Favourite Films\".
Now, we have to find the number of movie lists created by the user who has created the movie list \"250 Favourite Films\".",
"SQL": "SELECT COUNT(list_id) FROM lists_users WHERE user_id = ( SELECT user_id FROM lists WHERE list_title = '250 Favourite Films' )"}}

Q: For the user who post the list that contained the most number of the movies, is he/she a paying subscriber when creating that list?
Schema_links: [lists_users.user_has_payment_method, lists_users.list_id = lists.list_id, lists.list_movie_number, lists.list_movie_number]
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let's think step by step. the given question can be solved by knowing the answer to the following sub-questions = [which list has the most number of movies.]
The sqlite SQL query for the sub-question "which list has the most number of movies" is SELECT MAX(list_movie_number) FROM lists
The above query will return the list_movie_number of the list which has the most number of movies.
Now, we have to find the user_has_payment_method of the user who has created the list which has the most number of movies.
To do so, we have to JOIN lists_users and lists table on list_id.",
"SQL": "SELECT T1.user_has_payment_method FROM lists_users AS T1 INNER JOIN lists AS T2 ON T1.list_id = T2.list_id WHERE T2.list_movie_number = ( SELECT MAX(list_movie_number) FROM lists )"}}

Q: Which year was the third movie directed by Quentin Tarantino released? Indicate the user ids of the user who gave it a rating score of 4.
Schema_links: [movies.movie_release_year,ratings.user_id,ratings.rating_score,movies.movie_id = ratings.movie_id, movies.director_name, Quentin Tarantino, 4]
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let's think step by step. the given question can be solved by knowing the answer to the following sub-questions = [What is the third movie directed by Quentin Tarantino.]
The sqlite SQL query for the sub-question "what is third movie directed by Quentin Tarantino" is SELECT movie_id FROM movies WHERE director_name = 'Quentin Tarantino' ORDER BY movie_release_year ASC LIMIT 2, 1 
The above query will return the movie_id of the third movie directed by Quentin Tarantino.
Now, we have to find the year in which the third movie directed by Quentin Tarantino was released.
For that, we have to join the tables = [movies,ratings].
First of all, for joining these tables we have to use the common column = [movies.movie_id = ratings.movie_id].
Then, we have to filter the rows where movie_id = ( SELECT movie_id FROM movies WHERE director_name = 'Quentin Tarantino' ORDER BY movie_release_year ASC LIMIT 2, 1 ).
Then, we have to find the movie_release_year.",
"SQL": "SELECT T2.movie_release_year, T1.user_id FROM ratings AS T1 INNER JOIN movies AS T2 ON T1.movie_id = T2.movie_id WHERE T1.movie_id = ( SELECT movie_id FROM movies WHERE director_name = 'Quentin Tarantino' ORDER BY movie_release_year ASC LIMIT 2, 1 ) AND T1.rating_score = 4"}}
"""  # noqa: E501
SYSTEM_NESTED_CLASS_TEMPLATE_JOIN = """
Use the the schema links and intermediate reasoning steps to generate the correct sqlite SQL query for the given question.
Hint helps you to write the correct sqlite SQL query.
###
Few examples of this task are:
###
Schema of the database with sample rows and column descriptions:
#
CREATE TABLE lists (
        user_id INTEGER, 
        list_id INTEGER NOT NULL, 
        list_title TEXT, 
        list_movie_number INTEGER, 
        list_update_timestamp_utc TEXT, 
        list_creation_timestamp_utc TEXT, 
        list_followers INTEGER, 
        list_url TEXT, 
        list_comments INTEGER, 
        list_description TEXT, 
        list_cover_image_url TEXT, 
        list_first_image_url TEXT, 
        list_second_image_url TEXT, 
        list_third_image_url TEXT, 
        PRIMARY KEY (list_id), 
        FOREIGN KEY(user_id) REFERENCES lists_users (user_id)
)

/*
3 rows from lists table:
user_id list_id list_title      list_movie_number       list_update_timestamp_utc       list_creation_timestamp_utc     list_followers  list_url        list_commentslist_description list_cover_image_url    list_first_image_url    list_second_image_url   list_third_image_url
88260493        1       Films that made your kid sister cry     5       2019-01-24 19:16:18     2009-11-11 00:02:21     5       http://mubi.com/lists/films-that-made-your-kid-sister-cry     3       <p>Don’t be such a baby!!</p>
<p><strong>bold</strong></p>    https://assets.mubicdn.net/images/film/3822/image-w1280.jpg?1445914994  https://assets.mubicdn.net/images/film/3822/image-w320.jpg?1445914994 https://assets.mubicdn.net/images/film/506/image-w320.jpg?1543838422    https://assets.mubicdn.net/images/film/485/image-w320.jpg?1575331204
45204418        2       Headscratchers  3       2018-12-03 15:12:20     2009-11-11 00:05:11     1       http://mubi.com/lists/headscratchers    2       <p>Films that need at least two viewings to really make sense.</p>
<p>Or at least… they did for <em>       https://assets.mubicdn.net/images/film/4343/image-w1280.jpg?1583331932  https://assets.mubicdn.net/images/film/4343/image-w320.jpg?1583331932 https://assets.mubicdn.net/images/film/159/image-w320.jpg?1548864573    https://assets.mubicdn.net/images/film/142/image-w320.jpg?1544094102
48905025        3       Sexy Time Movies        7       2019-05-30 03:00:07     2009-11-11 00:20:00     6       http://mubi.com/lists/sexy-time-movies  5       <p>Films that get you in the mood…for love. In development.</p>
<p>Remarks</p>
<p><strong>Enter the    https://assets.mubicdn.net/images/film/3491/image-w1280.jpg?1564112978  https://assets.mubicdn.net/images/film/3491/image-w320.jpg?1564112978https://assets.mubicdn.net/images/film/2377/image-w320.jpg?1564675204    https://assets.mubicdn.net/images/film/2874/image-w320.jpg?1546574412
*/


CREATE TABLE lists_users (
        user_id INTEGER NOT NULL, 
        list_id INTEGER NOT NULL, 
        list_update_date_utc TEXT, 
        list_creation_date_utc TEXT, 
        user_trialist INTEGER, 
        user_subscriber INTEGER, 
        user_avatar_image_url TEXT, 
        user_cover_image_url TEXT, 
        user_eligible_for_trial TEXT, 
        user_has_payment_method TEXT, 
        PRIMARY KEY (user_id, list_id), 
        FOREIGN KEY(list_id) REFERENCES lists (list_id), 
        FOREIGN KEY(user_id) REFERENCES lists (user_id)
)

/*
3 rows from lists_users table:
user_id list_id list_update_date_utc    list_creation_date_utc  user_trialist   user_subscriber user_avatar_image_url   user_cover_image_url    user_eligible_for_trial       user_has_payment_method
85981819        1969    2019-11-26      2009-12-18      1       1       https://assets.mubicdn.net/images/avatars/74983/images-w150.jpg?1523895214      None    0    1
85981819        3946    2020-05-01      2010-01-30      1       1       https://assets.mubicdn.net/images/avatars/74983/images-w150.jpg?1523895214      None    0    1
85981819        6683    2020-04-12      2010-03-31      1       1       https://assets.mubicdn.net/images/avatars/74983/images-w150.jpg?1523895214      None    0    1
*/

CREATE TABLE ratings (
        movie_id INTEGER, 
        rating_id INTEGER, 
        rating_url TEXT, 
        rating_score INTEGER, 
        rating_timestamp_utc TEXT, 
        critic TEXT, 
        critic_likes INTEGER, 
        critic_comments INTEGER, 
        user_id INTEGER, 
        user_trialist INTEGER, 
        user_subscriber INTEGER, 
        user_eligible_for_trial INTEGER, 
        user_has_payment_method INTEGER, 
        FOREIGN KEY(movie_id) REFERENCES movies (movie_id), 
        FOREIGN KEY(user_id) REFERENCES lists_users (user_id), 
        FOREIGN KEY(rating_id) REFERENCES ratings (rating_id), 
        FOREIGN KEY(user_id) REFERENCES ratings_users (user_id)
)

/*
3 rows from ratings table:
movie_id        rating_id       rating_url      rating_score    rating_timestamp_utc    critic  critic_likes    critic_comments user_id user_trialist   user_subscriber       user_eligible_for_trial user_has_payment_method
1066    15610495        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/15610495 3       2017-06-10 12:38:33     None    0       0       41579158     00       1       0
1066    10704606        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10704606 2       2014-08-15 23:42:31     None    0       0       85981819     11       0       1
1066    10177114        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10177114 2       2014-01-30 13:21:57     None    0       0       4208563 0    01       1
*/

CREATE TABLE movies (
        movie_id INTEGER NOT NULL, 
        movie_title TEXT, 
        movie_release_year INTEGER, 
        movie_url TEXT, 
        movie_title_language TEXT, 
        movie_popularity INTEGER, 
        movie_image_url TEXT, 
        director_id TEXT, 
        director_name TEXT, 
        director_url TEXT, 
        PRIMARY KEY (movie_id)
)

/*
3 rows from movies table:
movie_id        movie_title     movie_release_year      movie_url       movie_title_language    movie_popularity        movie_image_url director_id     director_namedirector_url
1       La Antena       2007    http://mubi.com/films/la-antena en      105     https://images.mubicdn.net/images/film/1/cache-7927-1581389497/image-w1280.jpg  131  Esteban Sapir    http://mubi.com/cast/esteban-sapir
2       Elementary Particles    2006    http://mubi.com/films/elementary-particles      en      23      https://images.mubicdn.net/images/film/2/cache-512179-1581389841/image-w1280.jpg      73      Oskar Roehler   http://mubi.com/cast/oskar-roehler
3       It's Winter     2006    http://mubi.com/films/its-winter        en      21      https://images.mubicdn.net/images/film/3/cache-7929-1481539519/image-w1280.jpg82      Rafi Pitts      http://mubi.com/cast/rafi-pitts
*/

CREATE TABLE movies_join_ratings (
    movies_movie_id INTEGER,
    movie_title TEXT,
    movie_release_year INTEGER,
    movie_url TEXT,
    movie_title_language TEXT,
    movie_popularity INTEGER,
    movie_image_url TEXT,
    director_id TEXT,
    director_name TEXT,
    director_url TEXT,
    ratings_movie_id INTEGER,
    rating_id INTEGER,
    rating_url TEXT,
    rating_score INTEGER,
    rating_timestamp_utc TEXT,
    critic TEXT,
    critic_likes INTEGER,
    critic_comments INTEGER,
    user_id INTEGER,
    user_trialist INTEGER,
    user_subscriber INTEGER,
    user_eligible_for_trial INTEGER,
    user_has_payment_method INTEGER
)
/*
3 rows from movies_join_ratings table:
movies_movie_id	movie_title	movie_release_year	movie_url	movie_title_language	movie_popularity	movie_image_url	director_id	director_name	director_url	ratings_movie_id	rating_id	rating_url	rating_score	rating_timestamp_utc	critic	critic_likes	critic_comments	user_id	user_trialist	user_subscriber	user_eligible_for_trial	user_has_payment_method
1066	Pavee Lackeen: The Traveller Girl	2005	http://mubi.com/films/pavee-lackeen-the-traveller-girl	en	1	https://images.mubicdn.net/images/film/1066/cache-8564-1481540828/image-w1280.jpg	11337	Perry Ogden	http://mubi.com/cast/perry-ogden	1066	15610495	http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/15610495	3	2017-06-10 12:38:33	None	0	0	41579158	0	0	1	0
1066	Pavee Lackeen: The Traveller Girl	2005	http://mubi.com/films/pavee-lackeen-the-traveller-girl	en	1	https://images.mubicdn.net/images/film/1066/cache-8564-1481540828/image-w1280.jpg	11337	Perry Ogden	http://mubi.com/cast/perry-ogden	1066	10704606	http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10704606	2	2014-08-15 23:42:31	None	0	0	85981819	1	1	0	1
1066	Pavee Lackeen: The Traveller Girl	2005	http://mubi.com/films/pavee-lackeen-the-traveller-girl	en	1	https://images.mubicdn.net/images/film/1066/cache-8564-1481540828/image-w1280.jpg	11337	Perry Ogden	http://mubi.com/cast/perry-ogden	1066	10177114	http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10177114	2	2014-01-30 13:21:57	None	0	0	4208563	0	0	1	1
*/
#
Q: How many more movie lists were created by the user who created the movie list \"250 Favourite Films\"?
Schema_links: [lists_users.list_id, lists_users.user_id = lists.user_id, lists.list_title, 250 Favourite Films]
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let's think step by step. the given question can be solved by knowing the answer to the following sub-questions = [which user has created the movie list \"250 Favourite Films\".]
The sqlite SQL query for the sub-question "which user has created the movie list \"250 Favourite Films\"" is SELECT user_id FROM lists WHERE list_title = '250 Favourite Films'
The above query will return the user_id of the user who has created the movie list \"250 Favourite Films\".
Now, we have to find the number of movie lists created by the user who has created the movie list \"250 Favourite Films\".",
"SQL": "SELECT COUNT(list_id) FROM lists_users WHERE user_id = ( SELECT user_id FROM lists WHERE list_title = '250 Favourite Films' )"}}

Q: For the user who post the list that contained the most number of the movies, is he/she a paying subscriber when creating that list?
Schema_links: [lists_users.user_has_payment_method, lists_users.list_id = lists.list_id, lists.list_movie_number, lists.list_movie_number]
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let's think step by step. the given question can be solved by knowing the answer to the following sub-questions = [which list has the most number of movies.]
The sqlite SQL query for the sub-question "which list has the most number of movies" is SELECT MAX(list_movie_number) FROM lists
The above query will return the list_movie_number of the list which has the most number of movies.
Now, we have to find the user_has_payment_method of the user who has created the list which has the most number of movies.
To do so, we have to JOIN lists_users and lists table on list_id.",
"SQL": "SELECT T1.user_has_payment_method FROM lists_users AS T1 INNER JOIN lists AS T2 ON T1.list_id = T2.list_id WHERE T2.list_movie_number = ( SELECT MAX(list_movie_number) FROM lists )"}}

Q: Which year was the third movie directed by Quentin Tarantino released? Indicate the user ids of the user who gave it a rating score of 4.
Schema_links: [movies.movie_release_year,ratings.user_id,ratings.rating_score,movies.movie_id = ratings.movie_id, movies.director_name, Quentin Tarantino, 4]
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let's think step by step. the given question can be solved by knowing the answer to the following sub-questions = [What is the third movie directed by Quentin Tarantino.]
The sqlite SQL query for the sub-question "what is third movie directed by Quentin Tarantino" is SELECT movie_id FROM movies WHERE director_name = 'Quentin Tarantino' ORDER BY movie_release_year ASC LIMIT 2, 1 
The above query will return the movie_id of the third movie directed by Quentin Tarantino.
Now, we have to find the year in which the third movie directed by Quentin Tarantino was released.
For that, we have to join the tables = [movies,ratings].
First of all, for joining these tables we have to use the common column = [movies.movie_id = ratings.movie_id].
There is a join result table that is named movies_join_ratings which already has the join of these two tables, so we can use this table directly.
Then, we have to filter the rows where movie_id = ( SELECT movie_id FROM movies WHERE director_name = 'Quentin Tarantino' ORDER BY movie_release_year ASC LIMIT 2, 1 ).
Then, we have to find the movie_release_year.",
"SQL": "SELECT movie_release_year, user_id FROM movies_join_ratings WHERE movies_movie_id = ( SELECT movie_id FROM movies WHERE director_name = 'Quentin Tarantino' ORDER BY movie_release_year ASC LIMIT 2, 1 ) AND rating_score = 4"}}
"""  # noqa: E501
SYSTEM_NESTED_CLASS_TEMPLATE_JOIN_VIEW = """
Use the the schema links and intermediate reasoning steps to generate the correct sqlite SQL query for the given question.
Hint helps you to write the correct sqlite SQL query.
###
Few examples of this task are:
###
Schema of the database with sample rows and column descriptions:
#
CREATE TABLE lists (
        user_id INTEGER, 
        list_id INTEGER NOT NULL, 
        list_title TEXT, 
        list_movie_number INTEGER, 
        list_update_timestamp_utc TEXT, 
        list_creation_timestamp_utc TEXT, 
        list_followers INTEGER, 
        list_url TEXT, 
        list_comments INTEGER, 
        list_description TEXT, 
        list_cover_image_url TEXT, 
        list_first_image_url TEXT, 
        list_second_image_url TEXT, 
        list_third_image_url TEXT, 
        PRIMARY KEY (list_id), 
        FOREIGN KEY(user_id) REFERENCES lists_users (user_id)
)

/*
3 rows from lists table:
user_id list_id list_title      list_movie_number       list_update_timestamp_utc       list_creation_timestamp_utc     list_followers  list_url        list_commentslist_description list_cover_image_url    list_first_image_url    list_second_image_url   list_third_image_url
88260493        1       Films that made your kid sister cry     5       2019-01-24 19:16:18     2009-11-11 00:02:21     5       http://mubi.com/lists/films-that-made-your-kid-sister-cry     3       <p>Don’t be such a baby!!</p>
<p><strong>bold</strong></p>    https://assets.mubicdn.net/images/film/3822/image-w1280.jpg?1445914994  https://assets.mubicdn.net/images/film/3822/image-w320.jpg?1445914994 https://assets.mubicdn.net/images/film/506/image-w320.jpg?1543838422    https://assets.mubicdn.net/images/film/485/image-w320.jpg?1575331204
45204418        2       Headscratchers  3       2018-12-03 15:12:20     2009-11-11 00:05:11     1       http://mubi.com/lists/headscratchers    2       <p>Films that need at least two viewings to really make sense.</p>
<p>Or at least… they did for <em>       https://assets.mubicdn.net/images/film/4343/image-w1280.jpg?1583331932  https://assets.mubicdn.net/images/film/4343/image-w320.jpg?1583331932 https://assets.mubicdn.net/images/film/159/image-w320.jpg?1548864573    https://assets.mubicdn.net/images/film/142/image-w320.jpg?1544094102
48905025        3       Sexy Time Movies        7       2019-05-30 03:00:07     2009-11-11 00:20:00     6       http://mubi.com/lists/sexy-time-movies  5       <p>Films that get you in the mood…for love. In development.</p>
<p>Remarks</p>
<p><strong>Enter the    https://assets.mubicdn.net/images/film/3491/image-w1280.jpg?1564112978  https://assets.mubicdn.net/images/film/3491/image-w320.jpg?1564112978https://assets.mubicdn.net/images/film/2377/image-w320.jpg?1564675204    https://assets.mubicdn.net/images/film/2874/image-w320.jpg?1546574412
*/


CREATE TABLE lists_users (
        user_id INTEGER NOT NULL, 
        list_id INTEGER NOT NULL, 
        list_update_date_utc TEXT, 
        list_creation_date_utc TEXT, 
        user_trialist INTEGER, 
        user_subscriber INTEGER, 
        user_avatar_image_url TEXT, 
        user_cover_image_url TEXT, 
        user_eligible_for_trial TEXT, 
        user_has_payment_method TEXT, 
        PRIMARY KEY (user_id, list_id), 
        FOREIGN KEY(list_id) REFERENCES lists (list_id), 
        FOREIGN KEY(user_id) REFERENCES lists (user_id)
)

/*
3 rows from lists_users table:
user_id list_id list_update_date_utc    list_creation_date_utc  user_trialist   user_subscriber user_avatar_image_url   user_cover_image_url    user_eligible_for_trial       user_has_payment_method
85981819        1969    2019-11-26      2009-12-18      1       1       https://assets.mubicdn.net/images/avatars/74983/images-w150.jpg?1523895214      None    0    1
85981819        3946    2020-05-01      2010-01-30      1       1       https://assets.mubicdn.net/images/avatars/74983/images-w150.jpg?1523895214      None    0    1
85981819        6683    2020-04-12      2010-03-31      1       1       https://assets.mubicdn.net/images/avatars/74983/images-w150.jpg?1523895214      None    0    1
*/

CREATE TABLE ratings (
        movie_id INTEGER, 
        rating_id INTEGER, 
        rating_url TEXT, 
        rating_score INTEGER, 
        rating_timestamp_utc TEXT, 
        critic TEXT, 
        critic_likes INTEGER, 
        critic_comments INTEGER, 
        user_id INTEGER, 
        user_trialist INTEGER, 
        user_subscriber INTEGER, 
        user_eligible_for_trial INTEGER, 
        user_has_payment_method INTEGER, 
        FOREIGN KEY(movie_id) REFERENCES movies (movie_id), 
        FOREIGN KEY(user_id) REFERENCES lists_users (user_id), 
        FOREIGN KEY(rating_id) REFERENCES ratings (rating_id), 
        FOREIGN KEY(user_id) REFERENCES ratings_users (user_id)
)

/*
3 rows from ratings table:
movie_id        rating_id       rating_url      rating_score    rating_timestamp_utc    critic  critic_likes    critic_comments user_id user_trialist   user_subscriber       user_eligible_for_trial user_has_payment_method
1066    15610495        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/15610495 3       2017-06-10 12:38:33     None    0       0       41579158     00       1       0
1066    10704606        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10704606 2       2014-08-15 23:42:31     None    0       0       85981819     11       0       1
1066    10177114        http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10177114 2       2014-01-30 13:21:57     None    0       0       4208563 0    01       1
*/

CREATE TABLE movies (
        movie_id INTEGER NOT NULL, 
        movie_title TEXT, 
        movie_release_year INTEGER, 
        movie_url TEXT, 
        movie_title_language TEXT, 
        movie_popularity INTEGER, 
        movie_image_url TEXT, 
        director_id TEXT, 
        director_name TEXT, 
        director_url TEXT, 
        PRIMARY KEY (movie_id)
)

/*
3 rows from movies table:
movie_id        movie_title     movie_release_year      movie_url       movie_title_language    movie_popularity        movie_image_url director_id     director_namedirector_url
1       La Antena       2007    http://mubi.com/films/la-antena en      105     https://images.mubicdn.net/images/film/1/cache-7927-1581389497/image-w1280.jpg  131  Esteban Sapir    http://mubi.com/cast/esteban-sapir
2       Elementary Particles    2006    http://mubi.com/films/elementary-particles      en      23      https://images.mubicdn.net/images/film/2/cache-512179-1581389841/image-w1280.jpg      73      Oskar Roehler   http://mubi.com/cast/oskar-roehler
3       It's Winter     2006    http://mubi.com/films/its-winter        en      21      https://images.mubicdn.net/images/film/3/cache-7929-1481539519/image-w1280.jpg82      Rafi Pitts      http://mubi.com/cast/rafi-pitts
*/

CREATE VIEW `movies_join_ratings` AS
SELECT
  `movies`.`movie_id` AS `movies_movie_id`,
  `movies`.`movie_title`,
  `movies`.`movie_release_year`,
  `movies`.`movie_url`,
  `movies`.`movie_title_language`,
  `movies`.`movie_popularity`,
  `movies`.`movie_image_url`,
  `movies`.`director_id`,
  `movies`.`director_name`,
  `movies`.`director_url`,
  `ratings`.`movie_id` AS `ratings_movie_id`,
  `ratings`.`rating_id`,
  `ratings`.`rating_url`,
  `ratings`.`rating_score`,
  `ratings`.`rating_timestamp_utc`,
  `ratings`.`critic`,
  `ratings`.`critic_likes`,
  `ratings`.`critic_comments`,
  `ratings`.`user_id`,
  `ratings`.`user_trialist`,
  `ratings`.`user_subscriber`,
  `ratings`.`user_eligible_for_trial`,
  `ratings`.`user_has_payment_method`
FROM `movies`
JOIN `ratings` ON `ratings`.`movie_id` = `movies`.`movie_id` 

 /* 3 rows from movies_join_ratings: 
 movies_movie_id                movie_title movie_release_year                                      movie_url movie_title_language movie_popularity                                           movie_image_url director_id director_name                     director_url ratings_movie_id rating_id                                            rating_url rating_score rating_timestamp_utc critic critic_likes critic_comments  user_id user_trialist user_subscriber user_eligible_for_trial user_has_payment_method 
1066 Pavee Lackeen: The Traveller Girl                       2005 http://mubi.com/films/pavee-lackeen-the-traveller-girl                          en                                    1 https://images.mubicdn.net/images/film/1066/cache-8564-1481540828/image-w1280.jpg               11337           Perry Ogden http://mubi.com/cast/perry-ogden             1066          15610495 http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/15610495                    3           2017-06-10 12:38:33   None            0               0 41579158             0               0                       1                       0 
1066 Pavee Lackeen: The Traveller Girl                       2005 http://mubi.com/films/pavee-lackeen-the-traveller-girl                          en                                    1 https://images.mubicdn.net/images/film/1066/cache-8564-1481540828/image-w1280.jpg               11337           Perry Ogden http://mubi.com/cast/perry-ogden             1066          10704606 http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10704606                    2           2014-08-15 23:42:31   None            0               0 85981819             1               1                       0                       1 
1066 Pavee Lackeen: The Traveller Girl                       2005 http://mubi.com/films/pavee-lackeen-the-traveller-girl                          en                                    1 https://images.mubicdn.net/images/film/1066/cache-8564-1481540828/image-w1280.jpg               11337           Perry Ogden http://mubi.com/cast/perry-ogden             1066          10177114 http://mubi.com/films/pavee-lackeen-the-traveller-girl/ratings/10177114                    2           2014-01-30 13:21:57   None            0               0  4208563             0               0                       1                       1  
 */
#
Q: How many more movie lists were created by the user who created the movie list \"250 Favourite Films\"?
Schema_links: [lists_users.list_id, lists_users.user_id = lists.user_id, lists.list_title, 250 Favourite Films]
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let's think step by step. the given question can be solved by knowing the answer to the following sub-questions = [which user has created the movie list \"250 Favourite Films\".]
The sqlite SQL query for the sub-question "which user has created the movie list \"250 Favourite Films\"" is SELECT user_id FROM lists WHERE list_title = '250 Favourite Films'
The above query will return the user_id of the user who has created the movie list \"250 Favourite Films\".
Now, we have to find the number of movie lists created by the user who has created the movie list \"250 Favourite Films\".",
"SQL": "SELECT COUNT(list_id) FROM lists_users WHERE user_id = ( SELECT user_id FROM lists WHERE list_title = '250 Favourite Films' )"}}

Q: For the user who post the list that contained the most number of the movies, is he/she a paying subscriber when creating that list?
Schema_links: [lists_users.user_has_payment_method, lists_users.list_id = lists.list_id, lists.list_movie_number, lists.list_movie_number]
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let's think step by step. the given question can be solved by knowing the answer to the following sub-questions = [which list has the most number of movies.]
The sqlite SQL query for the sub-question "which list has the most number of movies" is SELECT MAX(list_movie_number) FROM lists
The above query will return the list_movie_number of the list which has the most number of movies.
Now, we have to find the user_has_payment_method of the user who has created the list which has the most number of movies.
To do so, we have to JOIN lists_users and lists table on list_id.",
"SQL": "SELECT T1.user_has_payment_method FROM lists_users AS T1 INNER JOIN lists AS T2 ON T1.list_id = T2.list_id WHERE T2.list_movie_number = ( SELECT MAX(list_movie_number) FROM lists )"}}

Q: Which year was the third movie directed by Quentin Tarantino released? Indicate the user ids of the user who gave it a rating score of 4.
Schema_links: [movies.movie_release_year,ratings.user_id,ratings.rating_score,movies.movie_id = ratings.movie_id, movies.director_name, Quentin Tarantino, 4]
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let's think step by step. the given question can be solved by knowing the answer to the following sub-questions = [What is the third movie directed by Quentin Tarantino.]
The sqlite SQL query for the sub-question "what is third movie directed by Quentin Tarantino" is SELECT movie_id FROM movies WHERE director_name = 'Quentin Tarantino' ORDER BY movie_release_year ASC LIMIT 2, 1 
The above query will return the movie_id of the third movie directed by Quentin Tarantino.
Now, we have to find the year in which the third movie directed by Quentin Tarantino was released.
For that, we have to join the tables = [movies,ratings].
First of all, for joining these tables we have to use the common column = [movies.movie_id = ratings.movie_id].
There is a join result table that is named movies_join_ratings which already has the join of these two tables, so we can use this table directly.
Then, we have to filter the rows where movie_id = ( SELECT movie_id FROM movies WHERE director_name = 'Quentin Tarantino' ORDER BY movie_release_year ASC LIMIT 2, 1 ).
Then, we have to find the movie_release_year.",
"SQL": "SELECT movie_release_year, user_id FROM movies_join_ratings WHERE movies_movie_id = ( SELECT movie_id FROM movies WHERE director_name = 'Quentin Tarantino' ORDER BY movie_release_year ASC LIMIT 2, 1 ) AND rating_score = 4"}}
"""  # noqa: E501
HUMAN_NESTED_CLASS_TEMPLATE = """
Use the the schema links and intermediate reasoning steps to generate the correct sqlite SQL query for the given question.
###
Schema of the database with sample rows and column descriptions:
#
{schema}

#
Q: {question}
Schema_links: {schema_links}
{history_block}{paths_block}A: Let's think step by step. the given question can be solved by knowing the answer to the following sub-questions = {sub_questions}
"""  # noqa: E501

SYSTEM_SELF_CORRECTION_PROMPT = """
For the given question, use the provided tables, columns, foreign keys, and primary keys to fix the given SQLite SQL QUERY for any issues. If there are any problems, fix them. If there are no issues, return the SQLite SQL QUERY as is.
Hint helps you to write the correct sqlite SQL query.
Use the following instructions for fixing the sqlite SQL query:
1) Avoid redundant columns in SELECT clause, all of the columns should be mentioned in the question.
2) Pay attention to the columns that are used for the JOIN by checking the Foreign keys.
3) Pay attention to the columns that are used for the WHERE statement.
4) Pay attention to the columns that are used for the GROUP BY statement.
5) Pay attention to the columns that are used for the ORDER BY statement.
6) check that all of the columns exist in the table and there are no typos.
7) Use CAST when is needed.
8) USE CASE WHEN is needed.
###
Few examples of this task are:
###
Schema of the database with sample rows and column descriptions:
#
CREATE TABLE movies (
        movie_id INTEGER NOT NULL, 
        movie_title TEXT, 
        movie_release_year INTEGER, 
        movie_url TEXT, 
        movie_title_language TEXT, 
        movie_popularity INTEGER, 
        movie_image_url TEXT, 
        director_id TEXT, 
        director_name TEXT, 
        director_url TEXT, 
        PRIMARY KEY (movie_id)
)

/*
3 rows from movies table:
movie_id        movie_title     movie_release_year      movie_url       movie_title_language    movie_popularity        movie_image_url director_id     director_namedirector_url
1       La Antena       2007    http://mubi.com/films/la-antena en      105     https://images.mubicdn.net/images/film/1/cache-7927-1581389497/image-w1280.jpg  131  Esteban Sapir    http://mubi.com/cast/esteban-sapir
2       Elementary Particles    2006    http://mubi.com/films/elementary-particles      en      23      https://images.mubicdn.net/images/film/2/cache-512179-1581389841/image-w1280.jpg      73      Oskar Roehler   http://mubi.com/cast/oskar-roehler
3       It's Winter     2006    http://mubi.com/films/its-winter        en      21      https://images.mubicdn.net/images/film/3/cache-7929-1481539519/image-w1280.jpg82      Rafi Pitts      http://mubi.com/cast/rafi-pitts
*/

#
Q: Name movie titles released in year 1945. Sort the listing by the descending order of movie popularity.
SQL: SELECT movie_title, movie_popularity FROM movies WHERE movie_release_year = 1945/01/01 ORDER BY movie_popularity DESC LIMIT 1
Please respond with a JSON object structured as follows:
{{"chain_of_thought_reasoning": "Let's think step by step to find the correct answer.
1) The column movie_popularity is not mentioned in the question so it's redundant.
2) JOIN is not required as there is no need to join any tables.
3) The condition movie_release_year = 1945/01/01 is not correct. The correct condition is movie_release_year = 1945.
4) GROUP BY is not required as there is no need to group any columns.
5) The ORDER BY clause is correct.
6) all columns are correct and there are no typo errors.
7) CAST is not required as there is no need to cast any columns.
8) CASE is not required as there is no need to use CASE.",
"Revised_SQL": "SELECT movie_title FROM movies WHERE movie_release_year = 1945 ORDER BY movie_popularity DESC LIMIT 1"}}
"""  # noqa: E501
HUMAN_SELF_CORRECTION_PROMPT = """
Evaluate the correctness of this query for the given question.
Correct it if there are any issues. If there are no issues, return the SQLite SQL QUERY as is.
Schema of the database with sample rows and column descriptions:
#
{schema}

#
Q: {question}
SQL: {sql_query}
{history_block}{paths_block}A: Let's think step by step to find the correct answer.""" # noqa: E501

# def get_database_schema(DB_URI: str) -> str:
#     """Get the database schema from the database URI

#     Args:
#         DB_URI (str): Database URI

#     Returns:
#         str: Database schema
#     """
#     db = SQLDatabase.from_uri("sqlite:///"+DB_URI)
#     db._sample_rows_in_table_info = 3
#     return db.get_table_info_no_throw()

# def get_database_schema(DB_URI: str, table_name: Union[str, List[str], None] = None, sample_rows: int = 3) -> str:
#     """Get the database schema from the database URI

#     Args:
#         DB_URI (str): Database URI
#         table_name (str | list, optional): If str, extract schema for that single table.
#                                            If list, extract schema for all tables in the list.
#                                            If None, extracts schema for all tables.
#         sample_rows (int): Number of sample rows to include. Set to 0 if datetime parsing errors occur.

#     Returns:
#         str: Database schema
#     """
#     db = SQLDatabase.from_uri("sqlite:///"+DB_URI, sample_rows_in_table_info=sample_rows)
    
#     if table_name is None:
#         return db.get_table_info_no_throw()
#     elif isinstance(table_name, str):
#         return db.get_table_info_no_throw(table_names=[table_name])
#     elif isinstance(table_name, list):
#         return db.get_table_info_no_throw(table_names=table_name)
#     else:
#         return db.get_table_info_no_throw()

def get_database_schema(DB_URI: str, table_name: Union[str, List[str], None] = None, sample_rows: int = 3, include_views: bool = False) -> str:
    """Get the database schema from the database URI

    Args:
        DB_URI (str): Database URI
        table_name (str | list, optional): If str, extract schema for that single table.
                                           If list, extract schema for all tables in the list.
                                           If None, extracts schema for all tables.
        sample_rows (int): Number of sample rows to include. Set to 0 if datetime parsing errors occur.
        include_views (bool): If True, include views in the schema. Default is False.

    Returns:
        str: Database schema
    """
    db = SQLDatabase.from_uri("sqlite:///"+DB_URI, sample_rows_in_table_info=sample_rows, view_support=include_views)

    if table_name is None:
        return db.get_table_info_no_throw()
    elif isinstance(table_name, str):
        return db.get_table_info_no_throw(table_names=[table_name])
    elif isinstance(table_name, list):
        return db.get_table_info_no_throw(table_names=table_name)
    else:
        return db.get_table_info_no_throw()


def get_database_schema_manual(db_path: str, table_names, sample_rows: int = 3) -> str:
    """Drop-in replacement for get_database_schema that mimics its output format
    but reads rows via a raw sqlite cursor (no SQLAlchemy type coercion).

    Produces `CREATE TABLE <name> (...)` — even for views — plus a `/* N rows from
    <name> table: ... */` sample block, matching langchain's SQLDatabase.get_table_info
    style. Used as a fallback when get_database_schema's fromisoformat tripping on
    DATE-as-int columns breaks the sqlalchemy path.
    """
    if isinstance(table_names, str):
        table_names = [table_names]

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    pieces = []

    for name in table_names:
        cols = cur.execute(f'PRAGMA table_info("{name}")').fetchall()
        if not cols:
            continue

        # Build column definition lines
        col_lines = []
        pks = []
        for cid, col_name, col_type, notnull, dflt, pk in cols:
            parts = [col_name]
            if col_type:
                parts.append(col_type)
            if notnull:
                parts.append("NOT NULL")
            if dflt is not None:
                parts.append(f"DEFAULT {dflt}")
            col_lines.append("\t" + " ".join(parts))
            if pk and pk > 0:
                pks.append((pk, col_name))

        # Composite / single PRIMARY KEY clause
        if pks:
            pk_names = ", ".join(n for _, n in sorted(pks))
            col_lines.append(f"\tPRIMARY KEY ({pk_names})")

        # FOREIGN KEY clauses (usually empty for views; included for parity with tables)
        try:
            fks = cur.execute(f'PRAGMA foreign_key_list("{name}")').fetchall()
        except sqlite3.DatabaseError:
            fks = []
        for fk in fks:
            # fk layout: (id, seq, ref_table, from_col, to_col, on_update, on_delete, match)
            col_lines.append(f"\tFOREIGN KEY({fk[3]}) REFERENCES {fk[2]} ({fk[4]})")

        create_stmt = (
            f"CREATE TABLE {name} (\n"
            + ", \n".join(col_lines)
            + "\n)"
        )

        # Sample rows block
        sample_block = ""
        if sample_rows and sample_rows > 0:
            try:
                rows = cur.execute(f'SELECT * FROM "{name}" LIMIT {int(sample_rows)}').fetchall()
            except Exception:
                rows = []
            col_names = [c[1] for c in cols]
            header = "\t".join(col_names)
            body_lines = [
                "\t".join("" if v is None else str(v) for v in row)
                for row in rows
            ]
            body = "\n".join(body_lines)
            sample_block = (
                f"\n\n/*\n{len(rows)} rows from {name} table:\n{header}\n{body}\n*/"
            )

        pieces.append(create_stmt + sample_block)

    conn.close()
    return "\n\n".join(pieces)

def get_database_schema_pg(
    DB_URI: str, 
    table_name: Union[str, List[str], None] = None, 
    sample_rows: int = 3, 
    include_views: bool = False,
    schema: str = "public"  # Added schema support for Postgres
) -> str:
    """Get the database schema from the PostgreSQL database URI

    Args:
        DB_URI (str): PostgreSQL URI (e.g., 'postgresql+psycopg2://user:pass@host:port/dbname')
        table_name (str | list, optional): Extract schema for specific table(s) or all if None.
        sample_rows (int): Number of sample rows to include.
        include_views (bool): If True, include views in the schema.
        schema (str): The specific PostgreSQL schema to reflect.

    Returns:
        str: Database schema
    """
    
    # Initialize LangChain's SQLDatabase with Postgres URI and target schema
    db = SQLDatabase.from_uri(
        DB_URI, 
        sample_rows_in_table_info=sample_rows, 
        view_support=include_views,
        schema=schema
    )
    
    if table_name is None:
        return db.get_table_info_no_throw()
    elif isinstance(table_name, str):
        return db.get_table_info_no_throw(table_names=[table_name])
    elif isinstance(table_name, list):
        return db.get_table_info_no_throw(table_names=table_name)
    else:
        return db.get_table_info_no_throw()
    
def extract_schema_links(input_text: str) -> List[str]:
    pattern = r'Schema_links:\s*\[(.*?)\]'
    match = re.search(pattern, input_text)
    if match:
        schema_links_str = match.group(1)
        schema_links = [link.strip() for link in schema_links_str.split(',')]
        return schema_links
    else:
        return []
    
def extract_label_and_sub_questions(input_text: str) -> Tuple[str, List[str]]:
    label_pattern = r'Label:\s*"(.*?)"'
    sub_questions_pattern = r'sub_questions:\s*\[(.*?)\]'

    label_match = re.search(label_pattern, input_text)
    sub_questions_match = re.search(sub_questions_pattern, input_text)

    label = label_match.group(1) if label_match else ""

    sub_questions = []
    if sub_questions_match:
        sub_questions_str = sub_questions_match.group(1)
        sub_questions = [question.strip() for question in sub_questions_str.split(',')]

    return label, sub_questions

def extract_sql_query(input_text):
    sql_pattern = r'SQL:\s*(.*?)$'
    match = re.search(sql_pattern, input_text, re.DOTALL)
    return match.group(1).strip() if match else None

def extract_revised_sql_query(input_text):
    sql_pattern = r'Revised_SQL:\s*(.*?)$'
    match = re.search(sql_pattern, input_text, re.DOTALL)
    return match.group(1).strip() if match else None

def update_json_file(json_filename, index, sql_query, db_id):
    try:
        with open(json_filename, 'r') as json_file:
            data = json.load(json_file)
    except FileNotFoundError:
        data = {}

    data[str(index)] = f"{sql_query}\t----- bird -----\t{db_id}"

    with open(json_filename, 'w') as json_file:
        json.dump(data, json_file, indent=4)

def table_descriptions_parser(database_dir):
    csv_files = glob.glob(f"{database_dir}/*.csv")
    # Iterate over the CSV files
    db_descriptions = ""
    for file_path in csv_files:
        table_name: str = os.path.basename(file_path).replace(".csv", "")
        db_descriptions += f"Table: {table_name}\n"
        table_df = pd.read_csv(file_path, encoding='latin-1')
        for _,row in table_df.iterrows():
           try:
                if pd.notna(row[2]):
                    col_description = re.sub(r'\s+', ' ', str(row[2]))  # noqa: E501
                    val_description = re.sub(r'\s+', ' ', str(row[4]))
                    if pd.notna(row[4]):
                        db_descriptions += f"Column {row[0]}: column description -> {col_description}, value description -> {val_description}\n"  # noqa: E501
                    else:
                        db_descriptions += f"Column {row[0]}: column description -> {col_description}\n"  # noqa: E501
           except Exception as e:
                print(e)
                db_descriptions += "No column description"
        db_descriptions += "\n"
    return db_descriptions

def extract_json_block(text: str):
        """
        Extracts the JSON object from a ChatGPT response that may contain reasoning,
        code fences, or extra commentary.
        """
        # If there's a ```json block, take only what's inside it
        text = text.replace(';\\"', ';"').replace('\\"SELECT', '"SELECT')
        if "```json" in text:
                # Grab everything between ```json and the next ```
                match = re.search(r"```json(.*?)```", text, re.DOTALL)
                if match:
                        return match.group(1).strip()
        
        # Otherwise, fallback: try to find first { ... } JSON block
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
                return match.group(0).strip()
        
        raise ValueError("No JSON found in response")

def list_tables_and_views(sqlite_path):
    """
    Returns a sorted list of all user-defined tables and views in a SQLite database.
    """
    conn = sqlite3.connect(sqlite_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type IN ('table', 'view')
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name;
    """)

    results = [row[0] for row in cursor.fetchall()]

    conn.close()
    return results

@func_set_timeout(90)
# ⭐ NEW optional alias parameters
def generate_schema_prompt(
    db_path,
    num_rows=None,
    no_join=False,
    target_table="all",
    extracted_values=None,
    alias_map=None,          # ⭐ NEW
    alias_namespace="workload"   # ⭐ NEW
):
    full_schema_prompt_list = []
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    if no_join:
        cursor.execute("""SELECT name FROM sqlite_master 
                          WHERE type='table' AND name != 'sqlite_sequence' 
                          AND name != 'sqlite_stat1' AND name not like '%_join_%';""")
    else:
        if target_table != "all":
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type in ('table', 'view') "
                "AND lower(name) = lower('{}');".format(target_table)
            )
        else:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type in ('table', 'view') "
                "AND name != 'sqlite_sequence' AND name != 'sqlite_stat1';"
            )

    tables = cursor.fetchall()
    schemas = {}

    if extracted_values is None:
        extracted_values = {}

    for table in tables:
        tname = table[0]
        if tname == "sqlite_sequence":
            continue

        # get original create SQL
        cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type in ('table','view') AND name=?",
            (tname,)
        )
        raw_sql = cursor.fetchone()[0]

        final_sql = raw_sql

        # ⭐ Inject inline alias comments inside CREATE TABLE body
        if alias_map and tname in alias_map:
            lines = raw_sql.split("\n")
            new_lines = []

            for line in lines:
                stripped = line.strip()
                tokens = stripped.split()

                if tokens:
                    raw_col_token = tokens[0].strip("`\"")  # ⭐ handles `id`, "id", id

                    if (
                        raw_col_token in alias_map[tname]
                        and alias_namespace in alias_map[tname][raw_col_token]
                        and "--" not in stripped
                    ):
                        alias_comment = alias_map[tname][raw_col_token][alias_namespace]
                        line = f"{line}    -- {alias_namespace} alias: {alias_comment}"

                new_lines.append(line)

            final_sql = "\n".join(new_lines)

        schemas[tname] = final_sql

        # ============================================================
        # existing row sample logic (unchanged)
        # ============================================================
        if num_rows:
            cur_table = tname
            cursor.execute("SELECT * FROM `{}` LIMIT {}".format(cur_table, num_rows))
            column_names = [description[0] for description in cursor.description]
            db_rows = cursor.fetchall()

            extracted_rows = []
            table_extracted = {
                col.split(".", 1)[1]: vals
                for col, vals in extracted_values.items()
                if col.split(".", 1)[0].lower() == cur_table.lower()
            }

            if table_extracted:
                max_len = max(len(vs) for vs in table_extracted.values())
                for i in range(max_len):
                    row_dict = {c: "" for c in column_names}
                    for col, vals in table_extracted.items():
                        if col in row_dict and i < len(vals):
                            row_dict[col] = vals[i]
                    extracted_rows.append(tuple(row_dict[c] for c in column_names))

            final_rows = list(db_rows) + extracted_rows

            rows_prompt = nice_look_table(column_names=column_names, values=final_rows)

            verbose_prompt = "/* \n {} rows from {}: \n {} \n */".format(
                len(final_rows), cur_table, rows_prompt
            )

            schemas[tname] = schemas[tname] + "\n\n" + verbose_prompt

    for _, v in schemas.items():
        full_schema_prompt_list.append(v)

    schema_prompt = "\n\n".join(full_schema_prompt_list)

    return schema_prompt

def nice_look_table(column_names: list, values: list):
    rows = []
    # Determine the maximum width of each column
    widths = [max(len(str(value[i])) for value in values + [column_names]) for i in range(len(column_names))]

    # Print the column names
    header = ''.join(f'{column.rjust(width)} ' for column, width in zip(column_names, widths))
    # print(header)
    # Print the values
    for value in values:
        row = ''.join(f'{str(v).rjust(width)} ' for v, width in zip(value, widths))
        rows.append(row)
    rows = "\n".join(rows)
    final_output = header + '\n' + rows
    return final_output

def filter_res_by_label(res, target_label):
    """
    Filters questions and indices from the results dictionary 
    based on a specific base_din_label.
    """
    # Short-circuit: if label is empty, return everything unfiltered
    if target_label != 'EASY' and target_label != 'NON-NESTED':
        return res['questions'], res['indices']
    # Use zip to iterate through aligned questions, indices, and labels
    filtered_data = [
        (q, i) for q, i, l in zip(res['questions'], res['indices'], res['labels'])
        if l == target_label
    ]
    
    # Unzip the filtered pairs back into two separate lists
    if not filtered_data:
        return [], []
    
    filtered_questions, filtered_indices = zip(*filtered_data)
    
    return list(filtered_questions), list(filtered_indices)

import psycopg2
def generate_schema_prompt_pg(db_config, num_rows=None, no_join=False, target_table="all", schema="public"):
    def get_foreign_keys(cursor, table_name):
        """
        Fetches foreign key constraints for a given table.
        Returns a list of (column_name, foreign_table, foreign_column).
        """
        cursor.execute("""
            SELECT
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
              ON tc.constraint_name = kcu.constraint_name
              AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage AS ccu
              ON ccu.constraint_name = tc.constraint_name
              AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_name = %s
              AND tc.table_schema = %s;
        """, (table_name, schema))
        return cursor.fetchall()

    def nice_look_table(column_names, values):
        lines = ["  " + "\t".join(column_names)]
        for row in values:
            lines.append("  " + "\t".join(str(x) for x in row))
        return "\n".join(lines)

    full_schema_prompt_list = []

    conn = psycopg2.connect(**db_config)
    cursor = conn.cursor()

    if no_join:
        cursor.execute(f"""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = %s AND table_type = 'BASE TABLE'
              AND table_name NOT ILIKE '%%_join_%%';
        """, (schema,))
    else:
        if target_table != "all":
            # cursor.execute(f"""
            #     SELECT table_name 
            #     FROM information_schema.tables 
            #     WHERE table_schema = %s 
            #       AND table_type IN ('BASE TABLE', 'VIEW') 
            #       AND lower(table_name) = lower(%s);
            # """, (schema, target_table))
            cursor.execute(f"""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = %s 
            AND table_type IN ('BASE TABLE', 'VIEW') 
            AND lower(table_name) = ANY(%s);
            """, (schema, [t.lower() for t in target_table]))
        else:
            cursor.execute(f"""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = %s 
                  AND table_type IN ('BASE TABLE', 'VIEW');
            """, (schema,))

    tables = cursor.fetchall()
    schemas = {}

    for (table_name,) in tables:
        # Detect whether it's a table or a view
        cursor.execute("""
            SELECT table_type
            FROM information_schema.tables
            WHERE table_schema = %s AND table_name = %s;
        """, (schema, table_name))
        table_type = cursor.fetchone()[0]

        cursor.execute("""
            SELECT obj_description(c.oid, 'pg_class')
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = %s AND n.nspname = %s;
        """, (table_name, schema))
        comment_res = cursor.fetchone()
        table_comment = comment_res[0] if comment_res and comment_res[0] else ""
        
        # Format the comment to sit nicely above the schema definition
        comment_str = f"-- Description: {table_comment}\n" if table_comment else ""

        if table_type == "VIEW":
            # Get actual view definition from pg_views
            cursor.execute("""
                SELECT definition
                FROM pg_views
                WHERE schemaname = %s AND viewname = %s;
            """, (schema, table_name))
            result = cursor.fetchone()

            if result:
                definition = result[0].strip()
                #create_stmt = f'CREATE VIEW "{table_name}" AS\n{definition};'
                create_stmt = f'{comment_str}CREATE VIEW "{table_name}" AS\n{definition};'
            else:
                create_stmt = f'-- WARNING: Could not retrieve definition for view "{table_name}"'

        else:  # BASE TABLE
            # Get column definitions
            cursor.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position;
            """, (schema, table_name))
            columns = cursor.fetchall()

            # Get foreign keys
            foreign_keys = get_foreign_keys(cursor, table_name)

            create_stmt_lines = [f'CREATE TABLE "{table_name}" (']
            create_stmt_lines += [f'  "{col[0]}" {col[1]}' for col in columns]

            for fk_col, ref_table, ref_col in foreign_keys:
                fk_clause = f'  FOREIGN KEY ("{fk_col}") REFERENCES "{ref_table}"("{ref_col}")'
                create_stmt_lines.append(fk_clause)
            create_stmt = create_stmt_lines[0] +"\n"
            create_stmt += ",\n".join(create_stmt_lines[1:]) + "\n);"

        # Optional sample data
        sample_data_prompt = ""
        if num_rows:
            try:
                cursor.execute(f'SELECT * FROM "{schema}"."{table_name}" LIMIT {num_rows};')
                values = cursor.fetchall()
                column_names = [desc[0] for desc in cursor.description]

                if values:
                    rows_prompt = nice_look_table(column_names=column_names, values=values)
                    sample_data_prompt = f"\n/* \n{len(values)} sample rows from {table_name}:\n{rows_prompt}\n*/"
            except Exception as e:
                print(f"Error reading rows from {table_name}: {e}")

        schemas[table_name] = f"{create_stmt}{sample_data_prompt}"

    for v in schemas.values():
        full_schema_prompt_list.append(v)

    cursor.close()
    conn.close()

    schema_prompt = "\n\n".join(full_schema_prompt_list)
    return schema_prompt



from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

# sample loaded inside main() when --history_path is provided
# Lazy-loaded — only initialized when --history_path is set (see ensure_bge_model)
model = None

def ensure_bge_model():
    """Lazy-load the BGE encoder; called only when history mode is active."""
    global model
    if model is None:
        model = SentenceTransformer('BAAI/bge-large-en-v1.5', device='cuda')
    return model

# 1️⃣ Prepare reference embeddings
def prepare_reference_embeddings(str_list, indices=None):
    """
    Compute embeddings for a list of strings.
    If 'indices' is provided, they are used; otherwise defaults to [0..N-1].
    Returns:
        ref_pairs: [(index, text), ...]
        embeddings: np.ndarray
    """
    if indices is None:
        indices = list(range(len(str_list)))
    else:
        # Safety: ensure lengths match
        assert len(indices) == len(str_list), (
            f"indices length ({len(indices)}) must match str_list length ({len(str_list)})"
        )

    #embeddings = model.encode(str_list, normalize_embeddings=True)
    _m = ensure_bge_model()
    texts = ["passage: " + str(s).strip() for s in str_list]       # ⭐ BGE improvement
    embeddings = _m.encode(texts, normalize_embeddings=True)
    ref_pairs = list(zip(indices, str_list))
    return ref_pairs, embeddings

# 2️⃣ Query top-K matches
def topk_embedding_cosine_sim(target_str, ref_pairs, ref_embeddings, top_k=5):
    """
    Compare target string against precomputed embeddings of (index, text) pairs.
    Returns: [(index, text, similarity_score)]
    """
    # Embed target
    #target_emb = model.encode([target_str], normalize_embeddings=True)
    _m = ensure_bge_model()
    target_emb = _m.encode(
        ["query: " + str(target_str).strip()],                    # ⭐ BGE improvement
        normalize_embeddings=True
    )

    # Compute cosine similarity
    similarities = cosine_similarity(target_emb, ref_embeddings).flatten()

    # Get top-K sorted indices
    top_idx = similarities.argsort()[::-1][:top_k]

    # Map back to (original index, text)
    results = [
        (ref_pairs[i][0], ref_pairs[i][1], float(similarities[i]))
        for i in top_idx
    ]
    return results

# (reference embedding prep moved into main() when --history_path is enabled)

import re
import ast
import itertools
from collections import Counter, defaultdict
from typing import List, Tuple, Dict, Set, Optional
from itertools import combinations, chain
from sentence_transformers import SentenceTransformer, util
import torch

# ------------------------------------------------------------
# 🧱 NORMALIZATION HELPERS
# ------------------------------------------------------------

def normalize_table_name(name: str) -> str:
    """Normalize table name for comparison (schema/quotes removed)."""
    name = re.sub(r'^[A-Z_]+\.', '', name)  # remove schema prefix like FIBEN.
    name = name.replace('"', '').replace("'", "")
    return name.strip().upper()

def _cluster_norm_cache(clusters) -> Dict[int, Set[str]]:
    """Return cluster_id -> normalized table-name set."""
    return {
        c["cluster_id"]: {normalize_table_name(t) for t in c["tables"]}
        for c in clusters
    }

# ------------------------------------------------------------
# 🔍 CLUSTER FINDING (STRICT)
# ------------------------------------------------------------

def find_best_cluster_combo_strict(query_tables, clusters):
    """
    Priority:
      1) Exact single-cluster match
      2) Subset of a single cluster (smallest cluster, then lowest ID)
      3) Subset of the union of two clusters (ONLY if no single superset)
         - minimize extras |union - qset|
         - minimize union size
         - lowest cluster IDs
      4) new
    """
    qset = {normalize_table_name(t) for t in query_tables}
    if not qset:
        return [], "new"

    clusters_sorted = sorted(clusters, key=lambda c: c["cluster_id"])
    norm_by_id = _cluster_norm_cache(clusters_sorted)

    # 1️⃣ exact
    for c in clusters_sorted:
        if qset == norm_by_id[c["cluster_id"]]:
            return [c], "exact"

    # 2️⃣ single superset
    supersets = [
        c for c in clusters_sorted if qset.issubset(norm_by_id[c["cluster_id"]])
    ]
    if supersets:
        supersets.sort(key=lambda c: (len(c["tables"]), c["cluster_id"]))
        return [supersets[0]], "subset"

    # 3️⃣ combination of two clusters (only if no single superset)
    candidates = [c for c in clusters_sorted if qset & norm_by_id[c["cluster_id"]]]
    best_pair, best_key = None, None  # (extras, union_size, id1, id2)
    for i, c1 in enumerate(candidates):
        s1 = norm_by_id[c1["cluster_id"]]
        for c2 in candidates[i + 1:]:
            s2 = norm_by_id[c2["cluster_id"]]
            union = s1 | s2
            if qset.issubset(union):
                extras = len(union - qset)
                key = (extras, len(union),
                       min(c1["cluster_id"], c2["cluster_id"]),
                       max(c1["cluster_id"], c2["cluster_id"]))
                if best_key is None or key < best_key:
                    best_key = key
                    best_pair = (c1, c2)
    if best_pair:
        return [best_pair[0], best_pair[1]], "subset_combo"

    # 4️⃣ no match → new cluster
    return [], "new"

# ------------------------------------------------------------
# 🧠 INITIAL CLUSTER CREATION
# ------------------------------------------------------------

def find_exact_query_patterns(list_of_table_lists, path_list, min_frequency=5, min_tables=4):
    """
    Build initial frequent table clusters. Case-insensitive keys so rows whose
    gt_tables differ only by casing (e.g. ['Match','Country'] vs ['match','country'])
    are counted as the same pattern. First-seen casing is preserved for the output.
    """
    exact_patterns = Counter()
    pattern_paths = defaultdict(set)
    pattern_repr = {}  # key -> list of original-case table names (first-seen wins)

    for tables, path in zip(list_of_table_lists, path_list):
        key = frozenset(t.lower() for t in tables)
        exact_patterns[key] += 1
        pattern_paths[key].add(path)
        if key not in pattern_repr:
            seen = {}
            for t in tables:
                seen.setdefault(t.lower(), t)
            pattern_repr[key] = list(seen.values())

    clusters = []
    cluster_id = 1
    for pattern, count in exact_patterns.items():
        if count >= min_frequency and len(pattern) >= min_tables:
            clusters.append({
                "cluster_id": cluster_id,
                "tables": sorted(pattern_repr[pattern]),
                "num_tables": len(pattern),
                "count": count,
                "paths": sorted(list(pattern_paths[pattern])),
                "questions": [],
                "indices": [],
                "match_types": [],
                "subsets": {},
                "combo_pairs": {},  # store idx -> (id1, id2) for subset_combo
                "labels": []
            })
            cluster_id += 1

    clusters.sort(key=lambda x: (x["count"], x["num_tables"]), reverse=True)
    return clusters

# ------------------------------------------------------------
# 🧩 ASSIGN QUERIES TO CLUSTERS
# ------------------------------------------------------------

#def assign_queries_to_clusters(list_of_table_lists, clusters, question_list, path_list, min_tables=4):
def assign_queries_to_clusters(list_of_table_lists, clusters, question_list, path_list, label_list, min_tables=4):
    """
    Additive assignment with strict combination matching.
    Each question belongs to exactly one cluster.
    For subset_combo, record the partner cluster id.
    """
    question_cluster_map = []
    question_combo_map = {}  # global idx -> (id1, id2)
    assigned_questions = set()
    next_cluster_id = max([c["cluster_id"] for c in clusters], default=0) + 1

    for idx, tables in enumerate(list_of_table_lists):
        if not tables or idx in assigned_questions:
            question_cluster_map.append(-1)
            continue

        matched, match_type = find_best_cluster_combo_strict(tables, clusters)
        #qtext, qpath = question_list[idx], path_list[idx]
        qtext, qpath, qlabel = question_list[idx], path_list[idx], label_list[idx] # Extract label
        # ---- Case 1: Exact or subset (single cluster)
        if len(matched) == 1:
            c = matched[0]
            c["indices"].append(idx)
            c["questions"].append(qtext)
            c["paths"].append(qpath)
            c["match_types"].append(match_type)
            c["labels"].append(qlabel) # Store the label
            question_cluster_map.append(c["cluster_id"])
            assigned_questions.add(idx)

        # ---- Case 2: Subset of combo of 2 clusters
        elif len(matched) == 2:
            c1, c2 = matched
            primary = c1 if c1["cluster_id"] < c2["cluster_id"] else c2
            partner = c2 if primary is c1 else c1

            primary["indices"].append(idx)
            primary["questions"].append(qtext)
            primary["paths"].append(qpath)
            primary["match_types"].append(match_type)
            primary["combo_pairs"][idx] = (primary["cluster_id"], partner["cluster_id"])
            primary["labels"].append(qlabel) # Store the label in primary

            question_combo_map[idx] = (primary["cluster_id"], partner["cluster_id"])
            question_cluster_map.append(primary["cluster_id"])
            assigned_questions.add(idx)

        # ---- Case 3: New cluster
        else:
            new_cluster = {
                "cluster_id": next_cluster_id,
                "tables": sorted(set(tables)),
                "num_tables": len(set(tables)),
                "count": 1,
                "paths": [qpath],
                "questions": [qtext],
                "indices": [idx],
                "match_types": ["new"],
                "subsets": {},
                "combo_pairs": {},
                "labels": [qlabel]
            }
            clusters.append(new_cluster)
            question_cluster_map.append(next_cluster_id)
            assigned_questions.add(idx)
            next_cluster_id += 1

    # Recompute counts
    for c in clusters:
        c["count"] = len(c["indices"])

    question_cluster_map = [[n] for n in question_cluster_map]
    for k, v in question_combo_map.items():
        question_cluster_map[k] = list(v)

    return question_cluster_map

# ------------------------------------------------------------
# 📊 SUBSET COMPUTATION
# ------------------------------------------------------------

def compute_subsets_inplace(clusters, list_of_table_lists, path_list):
    """Compute subsets per cluster (normalize only for matching)."""
    for c in clusters:
        subset_indices = defaultdict(list)
        cluster_norm = {normalize_table_name(t) for t in c["tables"]}
        extra_paths = set()

        for idx in c["indices"]:
            q_norm = frozenset(normalize_table_name(t) for t in list_of_table_lists[idx])
            if q_norm < cluster_norm:
                subset_indices[q_norm].append(idx)
                extra_paths.add(path_list[idx])

        c["paths"] = sorted(set(c["paths"]).union(extra_paths))
        c["subsets"] = {
            ", ".join(sorted(list(k))): v for k, v in subset_indices.items()
        }

# ------------------------------------------------------------
# ✅ USAGE EXAMPLE
# ------------------------------------------------------------

min_tables = 2
w_flag = "workload_updated_"
def simplify_sql(query: str) -> str:
    """
    Given a SQL string, return the same SQL but with:
    - Projections replaced by SELECT *
    - Anything after the FROM/JOINs removed (WHERE, GROUP BY, ORDER BY, LIMIT...)
    """
    # Normalize whitespace
    q = " ".join(query.strip().split())
    
    # Find FROM ... part
    match = re.search(r"\bFROM\b", q, re.IGNORECASE)
    if not match:
        raise ValueError("No FROM clause found in query")

    from_start = match.start()

    # Cut at FROM
    q_from = q[from_start:]

    # # Stop at first WHERE/GROUP BY/ORDER BY/LIMIT
    stop_match = re.search(r"\b(WHERE|GROUP BY|ORDER BY|HAVING|LIMIT)\b", q_from, re.IGNORECASE)
    if stop_match:
        q_from = q_from[:stop_match.start()]

    # Build simplified SQL
    simplified = f"{q_from.strip()}"
    return simplified
# cluster construction moved into build_clusters_from_history() — called from main()
    print(f"    Tables: {', '.join(c['tables'])}")

def normalize_table_name(name: str) -> str:
    """
    Normalize for equality/containment checks only.
    - Strip any schema prefix (lower/mixed/upper): schema.table -> table
    - Remove common quoting
    - Uppercase for robust matching
    """
    if name is None:
        return ""
    s = str(name).strip().strip('"').strip("'").strip('`').strip()
    # remove any single schema prefix like foo.bar (case-insensitive on characters)
    s = re.sub(r'^[A-Za-z0-9_]+\.', '', s)
    # also allow bracketed names [dbo].[Member] -> Member
    s = re.sub(r'^\[[^\]]+\]\.', '', s)
    return s.upper()

def _build_cluster_result(match_type, cluster_list, sqlite_path):
    """Merge cluster info and attach detected foreign keys (preserving original casing)."""
    tables = sorted(set(itertools.chain.from_iterable(c["tables"] for c in cluster_list)))
    paths  = sorted(set(itertools.chain.from_iterable(c.get("paths", []) for c in cluster_list)))
    cluster_ids = [c["cluster_id"] for c in cluster_list]

    fks = find_foreign_keys_between_tables(sqlite_path, tables) if sqlite_path else []

    return {
        "match_type": match_type,
        "cluster_ids": cluster_ids,
        "tables": tables,          # original casing from clusters
        "paths": paths,
        "foreign_keys": fks,       # original casing for table names
    }

def find_cluster_for_tables(query_tables, clusters, sqlite_path=None):
    """
    Guarantees: exact match first; otherwise find the minimal number of clusters
    whose union ⊇ query_tables (then minimize extras, then union size, then IDs).
    Output now matches find_all_clusters_for_tables (includes questions, indices).
    """
    qset = {normalize_table_name(t) for t in query_tables}
    if not qset:
        # 🔹 ADDED: include missing fields for consistency
        return {
            "match_type": "new",
            "cluster_ids": [],
            "tables": [],
            "paths": [],
            "foreign_keys": [],
            "questions": [],
            "indices": [],
        }

    clusters_sorted = sorted(clusters, key=lambda c: c["cluster_id"])
    norm_by_id = {
        c["cluster_id"]: {normalize_table_name(t) for t in c["tables"]}
        for c in clusters_sorted
    }

    # 1️⃣ Exact single cluster
    for c in clusters_sorted:
        if qset == norm_by_id[c["cluster_id"]]:
            # 🔹 ADDED: include questions + indices
            return _build_cluster_result("exact", [c], sqlite_path) | {
                "questions": c.get("questions", []),
                "indices": c.get("indices", []),
            }

    # 2️⃣ Single-cluster superset
    supersets = [c for c in clusters_sorted if qset.issubset(norm_by_id[c["cluster_id"]])]
    if supersets:
        supersets.sort(key=lambda c: (len(c["tables"]), c["cluster_id"]))
        c = supersets[0]
        # 🔹 ADDED: include questions + indices
        return _build_cluster_result("subset", [c], sqlite_path) | {
            "questions": c.get("questions", []),
            "indices": c.get("indices", []),
        }

    # 3️⃣ Minimal subset cover (fewest clusters)
    candidates = [c for c in clusters_sorted if qset & norm_by_id[c["cluster_id"]]]
    best_combo, best_key = None, None
    for r in range(2, len(candidates) + 1):
        for combo in combinations(candidates, r):
            u = set().union(*(norm_by_id[c["cluster_id"]] for c in combo))
            if qset.issubset(u):
                extras = len(u - qset)
                key = (r, extras, len(u), [c["cluster_id"] for c in combo])
                if best_key is None or key < best_key:
                    best_key, best_combo = key, combo
        if best_combo:
            break

    if best_combo:
        # 🔹 ADDED: merged questions + indices (like find_all_clusters_for_tables)
        all_questions = list(chain.from_iterable(c.get("questions", []) for c in best_combo))
        all_indices = list(chain.from_iterable(c.get("indices", []) for c in best_combo))
        seen_q, seen_i = set(), set()
        merged_q, merged_i = [], []
        for q, i in zip(all_questions, all_indices):
            if i not in seen_i and q not in seen_q:
                merged_q.append(q)
                merged_i.append(i)
                seen_q.add(q)
                seen_i.add(i)
        res = _build_cluster_result("subset_combo", list(best_combo), sqlite_path)
        res["questions"] = merged_q
        res["indices"] = merged_i
        return res

    # 4️⃣ No coverage → new
    # 🔹 ADDED: include missing fields
    return {
        "match_type": "new",
        "cluster_ids": [],
        "tables": [],
        "paths": [],
        "foreign_keys": [],
        "questions": [],
        "indices": [],
    }

def find_foreign_keys_between_tables(sqlite_path, tables):
    """
    Detect declared FKs via PRAGMA foreign_key_list for each table *as given*.
    - Membership checks use normalized names
    - Output preserves the original table names/casing provided in `tables`
    Returns: ["A.col=B.col", ...] with original table casing.
    """
    if not tables:
        return []

    # map normalized -> first seen original (for pretty printing)
    norm_to_orig = {}
    for t in tables:
        n = normalize_table_name(t)
        norm_to_orig.setdefault(n, t)

    norm_set = set(norm_to_orig.keys())
    out = set()

    conn = sqlite3.connect(sqlite_path)
    cur = conn.cursor()
    try:
        for t in tables:
            t_norm = normalize_table_name(t)
            # PRAGMA table name: keep original text; single quotes are ok for SQLite identifiers in PRAGMA
            try:
                cur.execute(f"PRAGMA foreign_key_list('{t}')")
                rows = cur.fetchall()
            except sqlite3.DatabaseError:
                rows = []

            for row in rows:
                # row layout: (id, seq, table, from, to, on_update, on_delete, match, ...)
                ref_table_raw = row[2]
                from_col = row[3]
                to_col   = row[4]

                ref_norm = normalize_table_name(ref_table_raw)
                if t_norm in norm_set and ref_norm in norm_set:
                    lhs = f"{norm_to_orig[t_norm]}.{from_col}"
                    rhs = f"{norm_to_orig[ref_norm]}.{to_col}"
                    out.add(f"{lhs}={rhs}")
    finally:
        conn.close()

    return sorted(out)


# ============================================================
# --view_adhoc helpers: LLM-generated CREATE VIEW on linked tables
# ============================================================
def find_fk_conditions_for_view_adhoc(db_path, tables, rename_mode=False,
                                      mapping_path=None, ds_org_tables=None,
                                      org_keyed=False):
    """FK condition strings between pairs of `tables` in the active namespace.

    Non-rename: PRAGMA foreign_key_list via find_foreign_keys_between_tables.
    Rename: translate original FKs to the renamed namespace and filter to `tables`.
    Returns sorted list like ['T1.col=T2.col', ...] (empty if none found).
    """
    if not tables or len(tables) < 2:
        return []
    if not rename_mode:
        return find_foreign_keys_between_tables(db_path, tables)
    if not ds_org_tables or not mapping_path:
        return []
    tset = {t.lower() for t in tables}
    table_to_view, view_org_to_renamed = load_rename_mapping(mapping_path, org_keyed)
    out = set()
    for from_t, from_c, ref_t, ref_c in fetch_org_fks(db_path, ds_org_tables):
        from_view = table_to_view.get(from_t.lower())
        ref_view = table_to_view.get(ref_t.lower())
        if not from_view or not ref_view:
            continue
        if from_view.lower() not in tset or ref_view.lower() not in tset:
            continue
        from_renamed = view_org_to_renamed.get(from_view, {}).get(from_c.lower())
        ref_renamed = view_org_to_renamed.get(ref_view, {}).get(ref_c.lower())
        if not from_renamed or not ref_renamed:
            continue
        out.add(f"{from_view}.{from_renamed}={ref_view}.{ref_renamed}")
    return sorted(out)


def create_adhoc_view(db_path, tables, fk_conditions, model, is_gemini,
                      num_rows=3, max_attempts=3, excluded_views=None):
    """Ask the LLM for a CREATE VIEW over `tables` using `fk_conditions`, run it,
    and return (view_name, view_schema_prompt). Returns (None, None) on failure.

    If the view already exists in the DB, reuse it (no drop/recreate) — but only if
    its name is NOT in `excluded_views` (the pre-defined org_views/renamed_views pool).
    If the intended view_name itself collides with an excluded name, bail out.
    """
    if len(tables) < 2 or not fk_conditions:
        return None, None
    view_name = "_join_".join(tables)

    excluded_lc = {v.lower() for v in (excluded_views or [])}
    if view_name.lower() in excluded_lc:
        print(f"[adhoc view] ⛔ intended name {view_name!r} collides with a pre-defined "
              f"(cluster) view — falling back to base schema")
        return None, None

    _CONN_TIMEOUT = 60  # seconds — raise from sqlite3 default (5s) to survive contention
    _BUSY_PRAGMA_MS = 30_000

    def _view_status():
        """Return 'missing' | 'valid' | 'broken' for view_name."""
        try:
            conn = sqlite3.connect(db_path, timeout=_CONN_TIMEOUT)
            cur = conn.cursor()
            try:
                cur.execute(f"PRAGMA busy_timeout = {_BUSY_PRAGMA_MS}")
                cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='view' AND lower(name)=lower(?)",
                    (view_name,),
                )
                row = cur.fetchone()
                if not row:
                    return "missing"
                try:
                    cur.execute(f"SELECT * FROM `{row[0]}` LIMIT 1")
                    cur.fetchone()
                    return "valid"
                except Exception:
                    return "broken"
            finally:
                cur.close(); conn.close()
        except Exception:
            return "missing"

    def _drop_view():
        try:
            conn = sqlite3.connect(db_path, check_same_thread=False, timeout=_CONN_TIMEOUT)
            cur = conn.cursor()
            cur.execute(f"PRAGMA busy_timeout = {_BUSY_PRAGMA_MS}")
            execute_sql(cur, f"DROP VIEW IF EXISTS `{view_name}`")
            cur.close(); conn.close()
            return True
        except Exception as _e:
            print(f"[adhoc view]    ⚠️  could not DROP broken view {view_name!r}: "
                  f"{type(_e).__name__}: {_e}")
            return False

    status = _view_status()
    if status == "valid":
        if view_name.lower() in excluded_lc:
            print(f"[adhoc view] ⛔ existing view {view_name!r} is in the pre-defined pool — "
                  f"refusing to reuse; falling back to base schema")
            return None, None
        print(f"[adhoc view] 🔁 reusing existing view {view_name!r} (valid, no recreate)")
        try:
            view_schema = generate_schema_prompt(
                db_path=db_path, num_rows=num_rows, no_join=False, target_table=view_name
            )
            return view_name, view_schema
        except Exception as e:
            print(f"[adhoc view]    ⚠️  reading existing view schema failed: "
                  f"{type(e).__name__}: {e} — dropping and recreating")
            _drop_view()
    elif status == "broken":
        print(f"[adhoc view] ⚠️  existing view {view_name!r} is BROKEN — dropping before recreate")
        _drop_view()

    base_pieces = []
    for t in tables:
        try:
            base_pieces.append(
                generate_schema_prompt(db_path=db_path, num_rows=num_rows,
                                       no_join=False, target_table=t)
            )
        except Exception:
            continue
    base_schema_for_prompt = "\n\n".join(base_pieces)

    prompt = f"""You are a database expert. Please give me the SQL script for creating the joined table on foreign keys.
The new view name should be in the format of `table1_join_table2` where table1 and table2 are the names of the tables that are joined together.
Keep all the original column, unless there is a name conflict.
In that case, change those columns from table1 into `table1_column`, and those columns from table2 into `table2_column`, only need to change the columns that has a name conflict.

Here is an example task:
###
Database Schema
CREATE TABLE Examination
(
    ID                 INTEGER          null,
    `Examination Date` DATE         null,
    `aCL IgG`          REAL        null,
    `aCL IgM`          REAL        null,
    ANA                INTEGER          null,
    `ANA Pattern`      TEXT null,
    `aCL IgA`          INTEGER          null,
    Diagnosis          TEXT null,
    KCT                TEXT null,
    RVVT               TEXT null,
    LAC                TEXT null,
    Symptoms           TEXT null,
    Thrombosis         INTEGER          null,
    foreign key (ID) references Patient (ID)
            on update cascade on delete cascade
)

CREATE TABLE Patient
(
    ID           INTEGER default 0 not null
        primary key,
    SEX          TEXT  null,
    Birthday     DATE          null,
    Description  DATE          null,
    `First Date` DATE          null,
    Admission    TEXT  null,
    Diagnosis    TEXT  null
)
###

Tables to be joined: ['Patient', 'Examination']
Join conditions: ['Examination.ID = Patient.ID']
New table name: Patient_join_Examination

Please respond with a JSON object structured as follows:

{{
    "chain_of_thought_reasoning": "The foreign key on these tables are the Patient.ID and Examination.ID and it is also in the join conditions. We need to join the Patient and Examination tables on the ID column. The new table name should be Patient_join_Examination. All columns from the Patient table has no conflict except the ID columns, so ID from Patient is renamed to Patient_ID, and ID from the Examination table is renamed to Examination_ID.",
    "SQL": "CREATE VIEW `Patient_join_Examination` AS SELECT `Patient`.`ID` AS `Patient_ID`, `Patient`.`SEX` AS `SEX`, `Patient`.`Birthday` AS `Birthday`, `Patient`.`Description` AS `Description`, `Patient`.`First Date` AS `First Date`, `Patient`.`Admission` AS `Admission`, `Patient`.`Diagnosis` AS `Diagnosis`, `Examination`.`ID` AS `Examination_ID`, `Examination`.`Examination Date` AS `Examination Date`, `Examination`.`aCL IgG` AS `aCL IgG`, `Examination`.`aCL IgM` AS `aCL IgM`, `Examination`.`ANA` AS `ANA`, `Examination`.`ANA Pattern` AS `ANA Pattern`, `Examination`.`aCL IgA` AS `aCL IgA`, `Examination`.`Diagnosis` AS `Diagnosis`, `Examination`.`KCT` AS `KCT`, `Examination`.`RVVT` AS `RVVT`, `Examination`.`LAC` AS `LAC`, `Examination`.`Symptoms` AS `Symptoms`, `Examination`.`Thrombosis` AS `Thrombosis` FROM `Patient` JOIN `Examination` ON `Examination`.`ID` = `Patient`.`ID`;"
}}

###
The new view name should be in the format of `table1_join_table2_join_...` where tables are joined together.
Keep all the original columns, unless there is a name conflict.
In that case, change those columns from tableA into `tableA_column`, and those columns from tableB into `tableB_column`, only need to change the columns that has a name conflict.
Now, here is a new schema for creating a new view:
{base_schema_for_prompt}

###

Tables to be joined: {list(tables)}
Join conditions: {fk_conditions}
New table name: {view_name}

Please respond with a JSON object structured as follows, and make sure each entry is there and follows the same format as the given format:
{{
    "chain_of_thought_reasoning": "Your thought process on how you arrived at the final SQL query",
    "SQL": "The CREATE VIEW SQL query for the new table based on the join conditions as well as the new column names."
}}

Carefully read the given schema, make sure all columns are there for the given table, do not hallucinate and mix up the columns between tables. If you follow all the instructions and answer correctly, I will give you 1 million dollars."""

    print(f"[adhoc view] 🛠️  creating view {view_name!r}")
    print(f"[adhoc view]    tables ({len(tables)}): {list(tables)}")
    print(f"[adhoc view]    fk_conditions ({len(fk_conditions)}): {fk_conditions}")
    print(f"[adhoc view]    model={model!r} (gemini={is_gemini})")

    for attempt in range(max_attempts):
        try:
            print(f"[adhoc view]    → LLM attempt {attempt + 1}/{max_attempts}")
            if is_gemini:
                resp = chat_with_gemini_DIN(prompt, model=model,
                                            response_fields={"SQL": str})
            else:
                resp = chat_with_chatgpt_DIN(prompt, model=model)
            if resp.find("```json") != -1:
                resp = resp[resp.find("```json"):]
            parsed = ast.literal_eval(resp.replace("```json", "").replace("```", ""))
            create_sql = parsed["SQL"]
            preview = " ".join(str(create_sql).split())
            print(f"[adhoc view]    LLM CREATE VIEW (first 200 chars): {preview[:200]}")

            # Defensive: drop any broken view left by a previous failed attempt so
            # the fresh CREATE VIEW doesn't collide with a stale registration.
            _drop_view()

            conn = sqlite3.connect(db_path, check_same_thread=False, timeout=_CONN_TIMEOUT)
            conn.text_factory = bytes
            cur = conn.cursor()
            try:
                cur.execute(f"PRAGMA busy_timeout = {_BUSY_PRAGMA_MS}")
                execute_sql(cur, create_sql)
            finally:
                cur.close()
                conn.close()

            view_schema = generate_schema_prompt(
                db_path=db_path, num_rows=num_rows, no_join=False, target_table=view_name
            )
            print(f"[adhoc view]    ✅ created {view_name!r} "
                  f"(schema {len(view_schema)} chars)")
            return view_name, view_schema
        except Exception as e:
            print(f"[adhoc view]    ❌ attempt {attempt + 1}/{max_attempts} failed: "
                  f"{type(e).__name__}: {e}")
            # Drop the broken view so it doesn't collide with the next attempt.
            _drop_view()
            continue
    print(f"[adhoc view]    ⛔ giving up on {view_name!r} after {max_attempts} attempts — "
          f"fall back to base schema")
    return None, None


# db_path now comes from --db_path in main()
def find_similar_question_cluster(
    question, clusters, question_cluster_map, model=None, top_k=1, sqlite_path=None
):
    """
    Returns top-k similar questions with their clusters, tables, paths, and FKs.
    FKs use original table casing.
    """
    if model is None:
        # model = SentenceTransformer('all-MiniLM-L6-v2',
        #                             device='cuda' if torch.cuda.is_available() else 'cpu')
        model = SentenceTransformer('BAAI/bge-large-en-v1.5',
                                    device='cuda' if torch.cuda.is_available() else 'cpu')
    # flatten all questions and keep their original indices
    all_questions, q_indices = [], []
    for c in clusters:
        for i, q in zip(c["indices"], c.get("questions", [])):
            all_questions.append(q)
            q_indices.append(i)

    if not all_questions:
        raise ValueError("No questions found in clusters.")

    all_embs = model.encode(all_questions, convert_to_tensor=True, normalize_embeddings=True)
    q_emb = model.encode(question, convert_to_tensor=True, normalize_embeddings=True)
    sims = util.cos_sim(q_emb, all_embs)[0]

    top_k = min(top_k, len(all_questions))
    top_indices = torch.topk(sims, k=top_k).indices.tolist()

    cluster_by_id = {c["cluster_id"]: c for c in clusters}
    results = []

    for idx in top_indices:
        sim_score = sims[idx].item()
        matched_question = all_questions[idx]
        original_idx = q_indices[idx]
        cluster_ids = question_cluster_map[original_idx] if original_idx < len(question_cluster_map) else []

        matched_tables, matched_paths = [], []
        for cid in cluster_ids:
            c = cluster_by_id.get(cid)
            if c:
                matched_tables.extend(c["tables"])         # keep original casing
                matched_paths.extend(c.get("paths", []))

        fks = find_foreign_keys_between_tables(sqlite_path, matched_tables) if sqlite_path else []

        results.append({
            "best_question": matched_question,
            "similarity": sim_score,
            "cluster_ids": cluster_ids,
            "tables": sorted(set(matched_tables)),         # original casing
            "paths": sorted(set(matched_paths)),
            "foreign_keys": fks,                           # original casing
        })

    return results
# (legacy find_similar_question_cluster test removed)
def find_all_clusters_for_tables(query_tables, clusters, sqlite_path=None):
    """
    Enhanced version:
    - Returns ALL clusters that contain one or more of the tables from query_tables.
    - Keeps same input/output type and backward-compatible fields.
    - Also returns aligned 'questions' and 'indices' fields:
        * de-duplicated while preserving order
        * ith question corresponds to ith index
    """
    qset = {normalize_table_name(t) for t in query_tables}
    if not qset:
        return {
            "match_type": "new",
            "cluster_ids": [],
            "tables": [],
            "paths": [],
            "foreign_keys": [],
            "questions": [],
            "indices": [],
        }

    clusters_sorted = sorted(clusters, key=lambda c: c["cluster_id"])
    norm_by_id = {
        c["cluster_id"]: {normalize_table_name(t) for t in c["tables"]}
        for c in clusters_sorted
    }

    # 1️⃣ Exact single cluster match
    for c in clusters_sorted:
        if qset == norm_by_id[c["cluster_id"]]:
            return _build_cluster_result("exact", [c], sqlite_path) | {
                "questions": c.get("questions", []),
                "indices": c.get("indices", []),
            }

    # 2️⃣ Single-cluster superset
    supersets = [c for c in clusters_sorted if qset.issubset(norm_by_id[c["cluster_id"]])]
    if supersets:
        supersets.sort(key=lambda c: (len(c["tables"]), c["cluster_id"]))
        c = supersets[0]
        return _build_cluster_result("subset", [c], sqlite_path) | {
            "questions": c.get("questions", []),
            "indices": c.get("indices", []),
        }

    # 3️⃣ All clusters with ANY overlap
    overlapping_clusters = [c for c in clusters_sorted if qset & norm_by_id[c["cluster_id"]]]
    if overlapping_clusters:
        # --- Merge and deduplicate questions/indices with order preserved ---
        all_questions = list(chain.from_iterable(c.get("questions", []) for c in overlapping_clusters))
        all_indices = list(chain.from_iterable(c.get("indices", []) for c in overlapping_clusters))

        seen_q, seen_i = set(), set()
        merged_q, merged_i = [], []

        for q, i in zip(all_questions, all_indices):
            if i not in seen_i and q not in seen_q:
                merged_q.append(q)
                merged_i.append(i)
                seen_q.add(q)
                seen_i.add(i)

        res = _build_cluster_result("partial", overlapping_clusters, sqlite_path)
        res["questions"] = merged_q
        res["indices"] = merged_i
        return res

    # 4️⃣ No overlap
    return {
        "match_type": "new",
        "cluster_ids": [],
        "tables": [],
        "paths": [],
        "foreign_keys": [],
        "questions": [],
        "indices": [],
    }

def find_all_clusters_for_tables(query_tables, clusters, sqlite_path=None):
    """
    Enhanced version (contract-correct):
    - Returns ALL clusters that contain one or more of the tables from query_tables.
    - Keeps same input/output type and backward-compatible fields.
    - Also returns aligned 'questions' and 'indices' fields:
        * de-duplicated while preserving order
        * ith question corresponds to ith index
    """
    qset = {normalize_table_name(t) for t in query_tables}
    if not qset:
        return {
            "match_type": "new",
            "cluster_ids": [],
            "tables": [],
            "paths": [],
            "foreign_keys": [],
            "questions": [],
            "indices": [],
            "labels": [],
        }

    clusters_sorted = sorted(clusters, key=lambda c: c["cluster_id"])
    norm_by_id = {
        c["cluster_id"]: {normalize_table_name(t) for t in c["tables"]}
        for c in clusters_sorted
    }

    # 1️⃣ Collect ALL clusters with ANY overlap
    overlapping_clusters = [
        c for c in clusters_sorted
        if (qset & norm_by_id[c["cluster_id"]])
    ]

    if not overlapping_clusters:
        return {
            "match_type": "new",
            "cluster_ids": [],
            "tables": [],
            "paths": [],
            "foreign_keys": [],
            "questions": [],
            "indices": [],
            "labels": [],  # Add this here for consistency
        }

    # 2️⃣ Determine match_type WITHOUT pruning overlap
    any_exact = any(qset == norm_by_id[c["cluster_id"]] for c in overlapping_clusters)
    any_subset = any(qset <  norm_by_id[c["cluster_id"]] for c in overlapping_clusters)

    if any_exact:
        match_type = "exact"
    elif any_subset:
        match_type = "subset"
    else:
        match_type = "partial"

    # 3️⃣ Merge questions + indices (aligned, de-duplicated, order preserved)
    seen_indices = set()
    merged_questions = []
    merged_indices = []
    merged_labels = []  # Initialize the list

    for c in overlapping_clusters:
        qs = c.get("questions", [])
        ix = c.get("indices", [])
        lb = c.get("labels", [])  # Retrieve the labels from the cluster
        #for q, i in zip(qs, ix):
        for q, i, l in zip(qs, ix, lb):
            if i not in seen_indices:
                merged_questions.append(q)
                merged_indices.append(i)
                merged_labels.append(l)  # Store the label
                seen_indices.add(i)

    # 4️⃣ Build final result using ALL overlapping clusters
    result = _build_cluster_result(match_type, overlapping_clusters, sqlite_path)
    result["questions"] = merged_questions
    result["indices"] = merged_indices
    result["labels"] = merged_labels  # Include the merged labels
    return result
# res = find_all_clusters_for_tables(ast.literal_eval(dev_df[f'gt_{w_flag}tables'][0]), exact_clusters, sqlite_path=db_path)
# print("------")
# print(res["cluster_ids"], res["match_type"])
# print("Foreign Keys:", res["foreign_keys"])



# ============================================================
# Prompt template objects (shared; built once)
# ============================================================
system_schema_linking_prompt = SystemMessagePromptTemplate.from_template(SYSTEM_SCHEMA_LINKING_TEMPLATE)
human_schema_linking_prompt = HumanMessagePromptTemplate.from_template(HUMAN_SCHEMA_LINKING_TEMPLATE)
schema_linking_prompt = ChatPromptTemplate.from_messages([system_schema_linking_prompt, human_schema_linking_prompt])

system_classification_prompt = SystemMessagePromptTemplate.from_template(SYSTEM_CLASSIFICATION_TEMPLATE)
human_classification_prompt = HumanMessagePromptTemplate.from_template(HUMAN_CLASSIFICATION_TEMPLATE)
classification_prompt = ChatPromptTemplate.from_messages([system_classification_prompt, human_classification_prompt])

system_easy_prompt = SystemMessagePromptTemplate.from_template(SYSTEM_EASY_CLASS_TEMPLATE)
human_easy_prompt = HumanMessagePromptTemplate.from_template(HUMAN_EASY_CLASS_TEMPLATE)
easy_prompt = ChatPromptTemplate.from_messages([system_easy_prompt, human_easy_prompt])

human_medium_prompt = HumanMessagePromptTemplate.from_template(HUMAN_NON_NESTED_CLASS_TEMPLATE)
human_hard_prompt = HumanMessagePromptTemplate.from_template(HUMAN_NESTED_CLASS_TEMPLATE)

system_correction_prompt = SystemMessagePromptTemplate.from_template(SYSTEM_SELF_CORRECTION_PROMPT)
human_correction_prompt = HumanMessagePromptTemplate.from_template(HUMAN_SELF_CORRECTION_PROMPT)
correction_prompt = ChatPromptTemplate.from_messages([system_correction_prompt, human_correction_prompt])


def make_non_nested_prompt(rename: bool, view: bool):
    """Build NON-NESTED prompt picking system template by flags.
    --view (±rename) → _JOIN_VIEW; otherwise → base.
    """
    if view:
        sys_tmpl = SYSTEM_NON_NESTED_CLASS_TEMPLATE_JOIN_VIEW
    else:
        sys_tmpl = SYSTEM_NON_NESTED_CLASS_TEMPLATE
    sys_msg = SystemMessagePromptTemplate.from_template(sys_tmpl)
    return ChatPromptTemplate.from_messages([sys_msg, human_medium_prompt])


def make_nested_prompt(rename: bool, view: bool):
    """Same flag→template mapping for NESTED.
    --view (±rename) → _JOIN_VIEW; otherwise → base.
    """
    if view:
        sys_tmpl = SYSTEM_NESTED_CLASS_TEMPLATE_JOIN_VIEW
    else:
        sys_tmpl = SYSTEM_NESTED_CLASS_TEMPLATE
    sys_msg = SystemMessagePromptTemplate.from_template(sys_tmpl)
    return ChatPromptTemplate.from_messages([sys_msg, human_hard_prompt])


# ============================================================
# Base table / view lists (CLI-controlled, per-dataset)
# ============================================================
# ----- SPIDER -----
spider_org_tables = ['conductor', 'orchestra', 'performance', 'show', 'airlines', 'airports', 'flights', 'Highschooler', 'Friend', 'Likes', 'players', 'matches', 'rankings', 'battle', 'ship', 'death', 'TV_Channel', 'TV_series', 'Cartoon', 'city', 'country', 'countrylanguage', 'course', 'teacher', 'course_arrange', 'Ref_Feature_Types', 'Ref_Property_Types', 'Other_Available_Features', 'Properties', 'Other_Property_Features', 'Ref_Template_Types', 'Templates', 'Documents', 'Paragraphs', 'continents', 'countries', 'car_makers', 'model_list', 'car_names', 'cars_data', 'poker_player', 'people', 'Addresses', 'Courses', 'Departments', 'Degree_Programs', 'Sections', 'Semesters', 'Students', 'Student_Enrolment', 'Student_Enrolment_Courses', 'Transcripts', 'Transcript_Contents', 'Breeds', 'Charges', 'Sizes', 'Treatment_Types', 'Owners', 'Dogs', 'Professionals', 'Treatments', 'Student', 'Has_Pet', 'Pets', 'employee', 'shop', 'hiring', 'evaluation', 'AREA_CODE_STATE', 'CONTESTANTS', 'stadium', 'singer', 'concert', 'singer_in_concert', 'museum', 'visitor', 'visit', 'VOTES']
spider_renamed_tables = ['conductors', 'orchestras', 'performances', 'shows', 'airline_companies', 'airport_locations', 'flight_schedules', 'highschoolers', 'friends', 'student_likes', 'tennis_players', 'tennis_matches', 'tennis_rankings', 'battles', 'ships', 'deaths', 'tv_channels', 'tv_series_episodes', 'cartoons', 'cities', 'countries_info', 'country_languages', 'courses_info', 'teachers', 'course_arrangements', 'feature_types', 'property_types', 'available_features', 'property_listings', 'property_features', 'template_types', 'document_templates', 'managed_documents', 'document_paragraphs', 'continent_info', 'car_countries', 'car_manufacturers', 'car_models', 'car_make_names', 'car_data', 'poker_players', 'people_info', 'student_addresses', 'university_courses', 'university_departments', 'degree_programs_info', 'course_sections', 'academic_semesters', 'university_students', 'student_enrollments', 'student_enrolled_courses', 'student_transcripts', 'transcript_contents_info', 'dog_breeds', 'vet_charges', 'dog_sizes', 'vet_treatment_types', 'dog_owners', 'vet_dogs', 'vet_professionals', 'vet_treatments', 'pet_students', 'student_has_pet', 'student_pets', 'shop_employees', 'retail_shops', 'shop_hiring', 'employee_evaluations', 'state_area_codes', 'voting_contestants', 'contestant_votes', 'stadiums', 'singers', 'concerts', 'concert_singers', 'museums', 'museum_visitors', 'museum_visits']
spider_org_views = ['cluster1_CARS_DATA_join_CAR_NAMES', 'cluster2_concert_join_stadium', 'cluster3_Documents_join_Templates', 'cluster4_Dogs_join_Treatments', 'cluster5_Professionals_join_Treatments', 'cluster6_Dogs_join_Owners', 'cluster7_AIRLINES_join_FLIGHTS', 'cluster8_AIRPORTS_join_FLIGHTS', 'cluster9_Friend_join_Highschooler', 'cluster10_Highschooler_join_Likes', 'cluster11_has_pet_join_student', 'cluster12_has_pet_join_pets_join_student', 'cluster13_people_join_poker_player', 'cluster14_TV_Channel_join_Cartoon', 'cluster15_country_join_countrylanguage', 'cluster16_death', 'cluster17_death_join_ship', 'cluster18_battle', 'cluster19_CAR_MAKERS_join_COUNTRIES', 'cluster20_continents', 'cluster21_CAR_MAKERS_join_MODEL_LIST', 'cluster22_singer', 'cluster23_concert_join_singer_in_concert', 'cluster24_teacher', 'cluster25_course_arrange_join_teacher', 'cluster26_course_join_course_arrange_join_teacher', 'cluster27_Documents_join_Paragraphs', 'cluster28_Ref_Template_Types', 'cluster29_Treatment_Types_join_Treatments_join_Professionals', 'cluster30_Breeds_join_Dogs', 'cluster31_Charges', 'cluster32_employee_join_evaluation', 'cluster33_hiring_join_shop', 'cluster34_visit_join_visitor', 'cluster35_museum', 'cluster36_orchestra', 'cluster37_show', 'cluster38_conductor_join_orchestra', 'cluster39_orchestra_join_performance', 'cluster40_Other_Available_Features_join_Ref_Feature_Types', 'cluster41_Properties_join_Ref_Property_Types', 'cluster42_Addresses', 'cluster43_Semesters_join_Student_Enrolment', 'cluster44_Courses_join_Sections', 'cluster45_Students', 'cluster46_Degree_Programs', 'cluster47_Transcript_Contents_join_Transcripts', 'cluster48_Courses_join_Student_Enrolment_Courses', 'cluster49_Degree_Programs_join_Departments', 'cluster50_Degree_Programs_join_Student_Enrolment_join_Students', 'cluster51_TV_series', 'cluster52_CONTESTANTS_join_VOTES', 'cluster53_AREA_CODE_STATE', 'cluster54_city_join_country_join_countrylanguage', 'cluster55_players', 'cluster56_matches', 'cluster57_rankings']
spider_renamed_views = ['cluster1_car_data_join_car_make_names', 'cluster2_car_countries_join_car_manufacturers', 'cluster3_car_manufacturers_join_car_models', 'cluster4_concerts_join_stadiums', 'cluster5_document_templates_join_managed_documents', 'cluster6_vet_dogs_join_vet_treatments', 'cluster7_vet_professionals_join_vet_treatments', 'cluster8_dog_owners_join_vet_dogs', 'cluster9_airline_companies_join_flight_schedules', 'cluster10_airport_locations_join_flight_schedules', 'cluster11_friends_join_highschoolers', 'cluster12_highschoolers_join_student_likes', 'cluster13_pet_students_join_student_has_pet', 'cluster14_pet_students_join_student_has_pet_join_student_pets', 'cluster15_people_info_join_poker_players', 'cluster16_cartoons_join_tv_channels', 'cluster17_countries_info_join_country_languages', 'cluster18_deaths', 'cluster19_deaths_join_ships', 'cluster20_battles', 'cluster21_continent_info', 'cluster22_singers', 'cluster23_concert_singers_join_concerts', 'cluster24_teachers', 'cluster25_course_arrangements_join_teachers', 'cluster26_course_arrangements_join_courses_info_join_teachers', 'cluster27_document_paragraphs_join_managed_documents', 'cluster28_template_types', 'cluster29_vet_professionals_join_vet_treatment_types_join_vet_treatments', 'cluster30_dog_breeds_join_vet_dogs', 'cluster31_vet_charges', 'cluster32_employee_evaluations_join_shop_employees', 'cluster33_retail_shops_join_shop_hiring', 'cluster34_museum_visitors_join_museum_visits', 'cluster35_museums', 'cluster36_orchestras', 'cluster37_shows', 'cluster38_conductors_join_orchestras', 'cluster39_orchestras_join_performances', 'cluster40_available_features_join_feature_types', 'cluster41_property_listings_join_property_types', 'cluster42_student_addresses', 'cluster43_academic_semesters_join_student_enrollments', 'cluster44_course_sections_join_university_courses', 'cluster45_university_students', 'cluster46_degree_programs_info', 'cluster47_student_transcripts_join_transcript_contents_info', 'cluster48_student_enrolled_courses_join_university_courses', 'cluster49_degree_programs_info_join_university_departments', 'cluster50_degree_programs_info_join_student_enrollments_join_university_students', 'cluster51_tv_series_episodes', 'cluster52_contestant_votes_join_voting_contestants', 'cluster53_state_area_codes', 'cluster54_cities_join_countries_info_join_country_languages', 'cluster55_tennis_players', 'cluster56_tennis_matches', 'cluster57_tennis_rankings']

# ----- BIRD -----
bird_org_tables = ['Country', 'Examination', 'Laboratory', 'League', 'Match', 'Patient', 'Player', 'Player_Attributes', 'Team', 'Team_Attributes', 'account', 'alignment', 'atom', 'attendance', 'attribute', 'badges', 'bond', 'budget', 'card', 'cards', 'circuits', 'client', 'colour', 'comments', 'connected', 'constructorResults', 'constructorStandings', 'constructors', 'customers', 'disp', 'district', 'driverStandings', 'drivers', 'event', 'expense', 'foreign_data', 'frpm', 'gasstations', 'gender', 'hero_attribute', 'hero_power', 'income', 'lapTimes', 'legalities', 'loan', 'major', 'member', 'molecule', 'order', 'pitStops', 'postHistory', 'postLinks', 'posts', 'products', 'publisher', 'qualifying', 'race', 'races', 'results', 'rulings', 'satscores', 'schools', 'seasons', 'set_translations', 'sets', 'status', 'superhero', 'superpower', 'tags', 'trans', 'transactions_1k', 'users', 'votes', 'yearmonth', 'zip_code']
bird_renamed_tables = ['Bank_Accounts', 'Bank_Cards', 'Bank_Clients', 'Bank_Dispositions', 'Bank_Districts', 'Bank_Loans', 'Bank_Orders', 'Bank_Transactions', 'Chem_Atoms', 'Chem_Bonds', 'Chem_Links', 'Chem_Molecules', 'Club_Attendance', 'Club_Budgets', 'Club_Events', 'Club_Expenses', 'Club_Income', 'Club_Majors', 'Club_Members', 'Club_Zips', 'Education_Lunch_Aid', 'Education_SAT_Stats', 'Education_Schools', 'Energy_Customers', 'Energy_Products', 'Energy_Sales', 'Energy_Stations', 'Energy_Usage', 'F1_Constructor_Results', 'F1_Constructor_Standings', 'F1_Constructors', 'F1_Driver_Standings', 'F1_Drivers', 'F1_Lap_Times', 'F1_Pit_Stops', 'F1_Qualifying', 'F1_Races', 'F1_Results', 'F1_Seasons', 'F1_Status_Codes', 'F1_Tracks', 'Forum_Badges', 'Forum_Comments', 'Forum_History', 'Forum_Links', 'Forum_Posts', 'Forum_Tags', 'Forum_Users', 'Forum_Votes', 'Hero_Alignments', 'Hero_Attribute_Types', 'Hero_Attributes', 'Hero_Colors', 'Hero_Genders', 'Hero_Power_Map', 'Hero_Profiles', 'Hero_Publishers', 'Hero_Races', 'Hero_Superpowers', 'MTG_Card_Foreign_Data', 'MTG_Cards', 'MTG_Legality', 'MTG_Rulings', 'MTG_Set_Translations', 'MTG_Sets', 'Medical_Exams', 'Medical_Lab_Results', 'Medical_Patients', 'Soccer_Countries', 'Soccer_Leagues', 'Soccer_Matches', 'Soccer_Player_Stats', 'Soccer_Players', 'Soccer_Team_Stats', 'Soccer_Teams']

bird_renamed_tables_0 = ['AcademicMajor', 'AccountDisposition', 'AccountTransaction', 'AthletePlayer', 'AtomConnectivity', 'BankAccount', 'BankClient', 'BankPaymentOrder', 'BiologicalGender', 'BiologicalRace', 'CaliforniaSchool', 'CardFormatLegality', 'CardOfficialRuling', 'CardSetCollection', 'CardTranslation', 'ChemicalBond', 'ChemicalMolecule', 'CommunityEvent', 'CreditLoan', 'DriverLapTiming', 'DriverSeasonStandings', 'EventAttendance', 'EventBudget', 'F1Driver', 'F1Season', 'ForumPost', 'ForumUser', 'FuelStation', 'FuelTransaction', 'GeographicCountry', 'GrandPrixRace', 'HeroAttributeValue', 'HeroMoralAlignment', 'HeroPowerAssignment', 'HeroPowerCapability', 'HeroTraitCategory', 'InventoryProduct', 'LabTestResults', 'LinkedPosts', 'MagicCard', 'MediaPublisher', 'MedicalExamination', 'MedicalPatient', 'MolecularAtom', 'MonthlyUtilityConsumption', 'OrganizationExpense', 'OrganizationIncome', 'OrganizationMember', 'PaymentCard', 'PitStopLog', 'PlayerSkillAttributes', 'PostComment', 'PostRevisionHistory', 'PostTagMetadata', 'PostVote', 'PostalLocation', 'QualifyingSession', 'RaceResultDetails', 'RaceStatusDescription', 'RaceTrackCircuit', 'RacingTeam', 'RegionalDemographics', 'RetailCustomer', 'SchoolPovertyFreeMeals', 'SchoolSATPerformance', 'SetTitleTranslation', 'SoccerMatch', 'SportsLeague', 'SportsTeam', 'SuperheroProfile', 'TeamPerformanceAttributes', 'TeamRaceResults', 'TeamSeasonStandings', 'UserBadge', 'VisualColor']
bird_org_views = ['cluster10_atom_join_bond_join_molecule', 'cluster11_cards_join_legalities', 'cluster12_cards_join_rulings', 'cluster13_cards_join_set_translations', 'cluster14_cards_join_foreign_data', 'cluster15_set_translations_join_sets', 'cluster16_cards_join_sets', 'cluster17_posts_join_users', 'cluster18_badges_join_users', 'cluster19_comments_join_posts', 'cluster1_frpm_join_schools', 'cluster20_posthistory_join_posts_join_users', 'cluster21_hero_power_join_superhero_join_superpower', 'cluster22_publisher_join_superhero', 'cluster23_colour_join_superhero', 'cluster24_race_join_superhero', 'cluster25_circuits_join_races', 'cluster26_drivers_join_qualifying', 'cluster27_races_join_results', 'cluster28_drivers_join_results', 'cluster29_driverstandings_join_drivers_join_races', 'cluster2_satscores_join_schools', 'cluster30_drivers_join_races_join_results', 'cluster31_league_join_match', 'cluster32_player_join_player_attributes', 'cluster33_team_join_team_attributes', 'cluster34_laboratory_join_patient', 'cluster35_examination_join_patient', 'cluster36_examination_join_laboratory_join_patient', 'cluster37_examination_join_laboratory', 'cluster38_major_join_member', 'cluster39_budget_join_event', 'cluster3_account_join_district', 'cluster40_member_join_zip_code', 'cluster41_expense_join_member', 'cluster42_customers_join_yearmonth', 'cluster43_gasstations_join_transactions_1k', 'cluster44_account_join_district_join_loan', 'cluster45_account_join_trans', 'cluster46_card_join_client_join_disp', 'cluster47_account_join_client_join_order', 'cluster48_posts_join_tags', 'cluster49_votes', 'cluster4_client_join_district', 'cluster50_postlinks_join_posts', 'cluster51_attribute_join_hero_attribute_join_publisher_join_superhero', 'cluster52_attribute_join_gender_join_hero_attribute_join_superhero', 'cluster53_alignment_join_superhero', 'cluster54_constructorstandings_join_constructors', 'cluster55_races_join_seasons', 'cluster56_drivers_join_laptimes', 'cluster57_races_join_results_join_status', 'cluster58_drivers_join_pitstops_join_races', 'cluster59_circuits_join_races_join_pitstops_join_results', 'cluster5_atom_join_bond', 'cluster60_country_join_league', 'cluster61_country_join_match_join_player', 'cluster62_attendance_join_event_join_member', 'cluster63_income_join_member', 'cluster64_customers_join_transactions_1k_join_products', 'cluster6_bond_join_molecule', 'cluster7_atom_join_connected', 'cluster8_atom_join_molecule', 'cluster9_bond_join_connected']
bird_renamed_views = ['workload_updated_cluster10_Chem_Atoms_join_Chem_Bonds_join_Chem_Molecules', 'workload_updated_cluster11_MTG_Cards_join_MTG_Legality', 'workload_updated_cluster12_MTG_Cards_join_MTG_Rulings', 'workload_updated_cluster13_MTG_Cards_join_MTG_Set_Translations', 'workload_updated_cluster14_MTG_Card_Foreign_Data_join_MTG_Cards', 'workload_updated_cluster15_MTG_Set_Translations_join_MTG_Sets', 'workload_updated_cluster16_MTG_Cards_join_MTG_Sets', 'workload_updated_cluster17_Forum_Posts_join_Forum_Users', 'workload_updated_cluster18_Forum_Badges_join_Forum_Users', 'workload_updated_cluster19_Forum_Comments_join_Forum_Posts', 'workload_updated_cluster1_Education_Lunch_Aid_join_Education_Schools', 'workload_updated_cluster20_Forum_History_join_Forum_Posts_join_Forum_Users', 'workload_updated_cluster21_Hero_Power_Map_join_Hero_Profiles_join_Hero_Superpowers', 'workload_updated_cluster22_Hero_Profiles_join_Hero_Publishers', 'workload_updated_cluster23_Hero_Colors_join_Hero_Profiles', 'workload_updated_cluster24_Hero_Profiles_join_Hero_Races', 'workload_updated_cluster25_F1_Races_join_F1_Tracks', 'workload_updated_cluster26_F1_Drivers_join_F1_Qualifying', 'workload_updated_cluster27_F1_Races_join_F1_Results', 'workload_updated_cluster28_F1_Drivers_join_F1_Results', 'workload_updated_cluster29_F1_Driver_Standings_join_F1_Drivers_join_F1_Races', 'workload_updated_cluster2_Education_SAT_Stats_join_Education_Schools', 'workload_updated_cluster30_F1_Drivers_join_F1_Races_join_F1_Results', 'workload_updated_cluster31_Soccer_Leagues_join_Soccer_Matches', 'workload_updated_cluster32_Soccer_Player_Stats_join_Soccer_Players', 'workload_updated_cluster33_Soccer_Team_Stats_join_Soccer_Teams', 'workload_updated_cluster34_Medical_Lab_Results_join_Medical_Patients', 'workload_updated_cluster35_Medical_Exams_join_Medical_Patients', 'workload_updated_cluster36_Medical_Exams_join_Medical_Lab_Results_join_Medical_Patients', 'workload_updated_cluster37_Medical_Exams_join_Medical_Lab_Results', 'workload_updated_cluster38_Club_Majors_join_Club_Members', 'workload_updated_cluster39_Club_Budgets_join_Club_Events', 'workload_updated_cluster3_Bank_Accounts_join_Bank_Districts', 'workload_updated_cluster40_Club_Members_join_Club_Zips', 'workload_updated_cluster41_Club_Expenses_join_Club_Members', 'workload_updated_cluster42_Energy_Customers_join_Energy_Usage', 'workload_updated_cluster43_Energy_Sales_join_Energy_Stations', 'workload_updated_cluster44_Bank_Accounts_join_Bank_Districts_join_Bank_Loans', 'workload_updated_cluster45_Bank_Accounts_join_Bank_Transactions', 'workload_updated_cluster46_Bank_Cards_join_Bank_Clients_join_Bank_Dispositions', 'workload_updated_cluster47_Bank_Accounts_join_Bank_Clients_join_Bank_Orders', 'workload_updated_cluster48_Forum_Posts_join_Forum_Tags', 'workload_updated_cluster49_Forum_Votes', 'workload_updated_cluster4_Bank_Clients_join_Bank_Districts', 'workload_updated_cluster50_Forum_Links_join_Forum_Posts', 'workload_updated_cluster51_Hero_Attribute_Types_join_Hero_Attributes_join_Hero_Profiles_join_Hero_Publishers', 'workload_updated_cluster52_Hero_Attribute_Types_join_Hero_Attributes_join_Hero_Genders_join_Hero_Profiles', 'workload_updated_cluster53_Hero_Alignments_join_Hero_Profiles', 'workload_updated_cluster54_F1_Constructor_Standings_join_F1_Constructors', 'workload_updated_cluster55_F1_Races_join_F1_Seasons', 'workload_updated_cluster56_F1_Drivers_join_F1_Lap_Times', 'workload_updated_cluster57_F1_Races_join_F1_Results_join_F1_Status_Codes', 'workload_updated_cluster58_F1_Drivers_join_F1_Pit_Stops_join_F1_Races', 'workload_updated_cluster59_F1_Pit_Stops_join_F1_Races_join_F1_Results_join_F1_Tracks', 'workload_updated_cluster5_Chem_Atoms_join_Chem_Bonds', 'workload_updated_cluster60_Soccer_Countries_join_Soccer_Leagues', 'workload_updated_cluster61_Soccer_Countries_join_Soccer_Matches_join_Soccer_Players', 'workload_updated_cluster62_Club_Attendance_join_Club_Events_join_Club_Members', 'workload_updated_cluster63_Club_Income_join_Club_Members', 'workload_updated_cluster64_Energy_Customers_join_Energy_Products_join_Energy_Sales', 'workload_updated_cluster6_Chem_Bonds_join_Chem_Molecules', 'workload_updated_cluster7_Chem_Atoms_join_Chem_Links', 'workload_updated_cluster8_Chem_Atoms_join_Chem_Molecules', 'workload_updated_cluster9_Chem_Bonds_join_Chem_Links']

# ----- Per-db_id table dicts (used by --per_db) -----
bird_db_dict = {'california_schools': ['frpm', 'satscores', 'schools'],
 'card_games': ['cards',
  'foreign_data',
  'legalities',
  'rulings',
  'sets',
  'set_translations'],
 'codebase_community': ['badges',
  'comments',
  'postHistory',
  'postLinks',
  'posts',
  'tags',
  'users',
  'votes'],
 'debit_card_specializing': ['customers',
  'gasstations',
  'products',
  'transactions_1k',
  'yearmonth'],
 'european_football_2': ['Country',
  'League',
  'Match',
  'Player',
  'Player_Attributes',
  'Team',
  'Team_Attributes'],
 'financial': ['account',
  'card',
  'client',
  'disp',
  'district',
  'loan',
  'order',
  'trans'],
 'formula_1': ['circuits',
  'constructorResults',
  'constructors',
  'constructorStandings',
  'drivers',
  'driverStandings',
  'lapTimes',
  'pitStops',
  'qualifying',
  'races',
  'results',
  'seasons',
  'status'],
 'student_club': ['attendance',
  'budget',
  'event',
  'expense',
  'income',
  'major',
  'member',
  'zip_code'],
 'superhero': ['alignment',
  'attribute',
  'colour',
  'gender',
  'hero_attribute',
  'hero_power',
  'publisher',
  'race',
  'superhero',
  'superpower'],
 'thrombosis_prediction': ['Examination', 'Laboratory', 'Patient'],
 'toxicology': ['atom', 'bond', 'connected', 'molecule']}

# TODO: placeholder — fill in with {db_id: [org_table_names]} for spider when needed
spider_db_dict = {}

# Lookup dict used by --dataset
DATASET_TABLES = {
    "spider": {
        "org_tables": spider_org_tables,
        "renamed_tables": spider_renamed_tables,
        "org_views": spider_org_views,
        "renamed_views": spider_renamed_views,
        "db_dict": spider_db_dict,
    },
    "bird": {
        "org_tables": bird_org_tables,
        "renamed_tables": bird_renamed_tables,
        "org_views": bird_org_views,
        "renamed_views": bird_renamed_views,
        "db_dict": bird_db_dict,
    },
}

# ============================================================
# History → cluster construction
# ============================================================
def build_clusters_from_history(history_path: str, sql_col: str, gt_tables_col: str,
                                sample_pct: int = 100, random_state: int = 42):
    """Load history sample CSV and build (sample, exact_clusters, question_cluster_map).

    sample_pct: 1..100; if <100, reproducibly sub-sample before clustering.
    """
    sample = pd.read_csv(history_path)
    if sample_pct < 100:
        full_n = len(sample)
        sample = sample.sample(frac=sample_pct / 100.0, random_state=random_state).reset_index(drop=True)
        print(f"🎲 Sub-sampled history: kept {len(sample)}/{full_n} rows ({sample_pct}%, seed={random_state})")
        if len(sample) > 0:
            _first_q   = str(sample.iloc[0].get("question", "<no question col>"))
            _first_sql = str(sample.iloc[0].get(sql_col, f"<no {sql_col!r} col>"))
            print(f"    first question: {_first_q!r}")
            print(f"    first SQL ({sql_col}): {_first_sql!r}")

    path_list = [simplify_sql(s) for s in sample[sql_col].tolist()]
    question_list = list(sample['question'])
    t_list = [ast.literal_eval(x) for x in list(sample[gt_tables_col])]

    # DIN's assign_queries_to_clusters requires a label_list; pass dummies since
    # we don't use label-based narrowing (mirrors run_spider.py behavior).
    label_list = [""] * len(t_list)

    exact_clusters = find_exact_query_patterns(t_list, path_list, min_frequency=5, min_tables=2)
    question_cluster_map = assign_queries_to_clusters(
        t_list, exact_clusters, question_list, path_list, label_list, min_tables=2
    )
    compute_subsets_inplace(exact_clusters, t_list, path_list)

    print(f"✅ Total clusters built from history: {len(exact_clusters)}")
    return sample, exact_clusters, question_cluster_map


# ============================================================
# CLI parsing
# ============================================================
def parse_args():
    p = argparse.ArgumentParser(description="Run DIN-SQL NL2SQL pipeline (linking → classify → gen → correct)")
    p.add_argument("--dataset", choices=["spider", "bird"], default="spider",
                   help="Dataset to run on. Controls table/view lists and log folder. Default: spider.")
    p.add_argument("--model", default="gpt-4.1-mini",
                   help="Model name for stages 2/3/4. Any string starting with 'gemini' uses "
                        "Google GenAI; anything else uses OpenAI. Default: gpt-4.1-mini.")
    p.add_argument("--csv_path", default=None,
                   help="Path to nl2sql CSV (input questions). If omitted, defaults to "
                        "../../csvs/nl2sql_{dataset}.csv (relative to this script).")
    p.add_argument("--db_path", default=None,
                   help="Path to the SQLite database file. If omitted, defaults to "
                        "../../databases/merged_{dataset}.sqlite (relative to this script).")
    p.add_argument("--history", action="store_true",
                   help="Enable history mode. When set with no --history_path, defaults to "
                        "../../csvs/sample_{dataset}.csv (relative to this script). "
                        "Passing --history_path implicitly enables history mode.")
    p.add_argument("--history_path", default=None,
                   help="Path to sample/history CSV. Implies --history when provided. "
                        "If --history is set without this flag, defaults to "
                        "../../csvs/sample_{dataset}.csv.")
    p.add_argument("--sample", type=int, default=100, metavar="N",
                   help="Integer 1..100; percent of the history CSV to use. <100 triggers a "
                        "reproducible random sub-sample (seed=42) before clusters/embeddings. "
                        "For --dataset bird, N<100 also auto-maps bird_renamed_tables_N / "
                        "bird_renamed_views_N / bird_org_views_N / name_mapping_bird_N.json when "
                        "--rename_v / --view_v / --mapping_path are not explicitly set. Default 100.")
    p.add_argument("--rename", action="store_true",
                   help="Use renamed_tables/renamed_views instead of org_tables/org_views. "
                        "With --rename, base schema is built via get_database_schema; "
                        "stage-3 picks the _JOIN template variant.")
    p.add_argument("--rename_v", default=None, metavar="VAR",
                   help="Name of a module-level Python variable (a list) whose contents "
                        "override the default renamed-tables list (e.g. --rename_v bird_renamed_tables_0). "
                        "Only used with --rename. If unset, falls back to the dataset's default.")
    p.add_argument("--view", action="store_true",
                   help="Add matching views (picked per question via Stage-1 table → view-name parsing) "
                        "to the schema. Stage-3 picks the _JOIN_VIEW template variant.")
    p.add_argument("--view_v", default=None, metavar="VAR",
                   help="Name of a module-level Python variable (a list of view names) to use "
                        "as the views pool, overriding the dataset default and any auto-derived "
                        "pool from --rename_v. Requires --view.")
    p.add_argument("--view_adhoc", action="store_true",
                   help="Ad-hoc view creation (requires --view and --use_linking). "
                        "Reads linked tables from --use_linking (stage 0), asks the LLM for a "
                        "CREATE VIEW joining them on foreign keys, creates the view in the DB, "
                        "and injects the view's schema into all stages. Stage 1 still runs. "
                        "Suffix '_uselinking' → '_adhoclinking'.")
    p.add_argument("--view_relink", action="store_true",
                   help="Re-link mode (requires --view and --use_linking). Reads linked tables "
                        "from --use_linking (stage 0), picks matching pre-defined views (same as "
                        "plain --view), injects those view schemas into stage 1, runs stage 1 to "
                        "produce a fresh linking, then uses the same augmented schema for later "
                        "stages. If <2 linked tables or no matching views, stage 1 is skipped. "
                        "Mutually exclusive with --view_adhoc. Suffix '_uselinking' → '_relinking'.")
    p.add_argument("--cluster", action="store_true",
                   help="Inject matching clusters' common join paths into stages 2/3/4. When "
                        "combined with --history_path, also restricts top-K history retrieval to "
                        "questions belonging to the matched clusters.")
    p.add_argument("--cluster_filter", action="store_true",
                   help="Restrict the stage-2/3/4 schema (and --view matched views / --view_adhoc "
                        "view reuse) to only the tables that belong to the matched clusters. "
                        "Stage 1 is unaffected. Requires --cluster. If no clusters match for a "
                        "question, falls back to the full schema for that question.")
    p.add_argument("--use_linking", default=None, metavar="COLUMN",
                   help="Column name in input CSV with pre-computed schema links. "
                        "When set, stage 1 is skipped; stages 2/3/4 still run fresh.")
    p.add_argument(
        "--mapping_path", default=None,
        help="Path to the name-mapping JSON (e.g. name_mapping_spider.json or name_mapping_bird.json). "
             "Only used when --rename is set. Default: auto-selected per --dataset.",
    )
    p.add_argument("--per_db", action="store_true",
                   help="Per-db mode: restrict base schema, views pool, clusters, and history "
                        "retrieval to each question's db_id (read from the 'db_id' column). "
                        "Requires DATASET_TABLES[dataset]['db_dict'] to be populated. "
                        "Unknown db_ids fall back to the full union with a warning.")
    p.add_argument("--rows", default=None, metavar="SPEC",
                   help="Row selection. 'N' for first N rows, or 'START:END' for a slice.")
    return p.parse_args()


# ============================================================
# Main
# ============================================================
def main():
    args = parse_args()

    # Auto-resolve csv_path / db_path / history_path from --dataset when not explicitly provided.
    # This script is expected to run from <LDD_ROOT>/benchmarks/spider_data/, so the shared data
    # folders (databases/, mapping_files/, csvs/) sit two levels up.
    _this_dir = os.path.dirname(os.path.abspath(__file__))                   # .../benchmarks/spider_data/
    _ldd_root = os.path.abspath(os.path.join(_this_dir, "..", ".."))         # .../Logical-Database-Design/
    if args.csv_path is None:
        args.csv_path = os.path.join(_ldd_root, "csvs", f"nl2sql_{args.dataset}.csv")
        print(f"[run_spider_din] --csv_path auto-resolved to {args.csv_path}")
    if args.db_path is None:
        args.db_path = os.path.join(_ldd_root, "databases", f"merged_{args.dataset}.sqlite")
        print(f"[run_spider_din] --db_path auto-resolved to {args.db_path}")

    # History gating: --history_path implies --history; --history alone uses the default file;
    # neither flag → history mode disabled.
    if args.history_path:
        args.history = True
    elif args.history:
        args.history_path = os.path.join(_ldd_root, "csvs", f"sample_{args.dataset}.csv")
        if not os.path.exists(args.history_path):
            raise SystemExit(
                f"--history requested but default sample file not found at {args.history_path}. "
                f"Pass --history_path explicitly or drop --history."
            )
        print(f"[run_spider_din] --history_path auto-resolved to {args.history_path}")
    else:
        args.history_path = None

    for _label, _path in (("--csv_path", args.csv_path), ("--db_path", args.db_path)):
        if not os.path.exists(_path):
            raise SystemExit(f"{_label} not found at {_path}. Pass {_label} explicitly.")
    db_path = args.db_path

    if args.cluster and not args.history_path:
        raise SystemExit("--cluster requires --history_path (clusters are built from the sample CSV).")
    if args.cluster_filter and not args.cluster:
        raise SystemExit("--cluster_filter requires --cluster.")
    if args.view_adhoc:
        if not args.view:
            raise SystemExit("--view_adhoc requires --view.")
        if not args.use_linking:
            raise SystemExit("--view_adhoc requires --use_linking.")
    if args.view_relink:
        if not args.view:
            raise SystemExit("--view_relink requires --view.")
        if not args.use_linking:
            raise SystemExit("--view_relink requires --use_linking.")
        if args.view_adhoc:
            raise SystemExit("--view_relink and --view_adhoc are mutually exclusive.")
    if args.rename_v and not args.rename:
        raise SystemExit("--rename_v requires --rename.")
    if args.view_v and not args.view:
        raise SystemExit("--view_v requires --view.")
    if not (1 <= args.sample <= 100):
        raise SystemExit(f"--sample must be between 1 and 100, got {args.sample}")
    if args.sample != 100 and not args.history_path:
        raise SystemExit("--sample <100 requires --history_path (sampling applies to the history CSV).")

    # ----- --sample N: auto-map _N variants for bird/spider when not explicitly overridden -----
    # Explicit --rename_v / --view_v / --mapping_path always win; --sample fills the gaps.
    if args.sample != 100 and args.dataset in ("bird", "spider"):
        _s = str(args.sample)
        _rt  = f"{args.dataset}_renamed_tables_{_s}"
        _rv  = f"{args.dataset}_renamed_views_{_s}"
        _ov  = f"{args.dataset}_org_views_{_s}"
        _map = f"name_mapping_{args.dataset}_{_s}.json"
        _script_dir = os.path.dirname(os.path.abspath(__file__))             # .../benchmarks/spider_data/
        # Mapping files live at <LDD_ROOT>/mapping_files (two levels up from this script).
        _ldd_mapping_dir = os.path.abspath(os.path.join(_script_dir, "..", "..", "mapping_files"))

        missing = []
        if globals().get(_rt) is None: missing.append(f"module variable {_rt!r}")
        if globals().get(_rv) is None: missing.append(f"module variable {_rv!r}")
        if globals().get(_ov) is None: missing.append(f"module variable {_ov!r}")
        if not (os.path.exists(os.path.join(_ldd_mapping_dir, _map))
                or os.path.exists(os.path.join(_script_dir, _map))):
            missing.append(f"mapping file {_map!r} (looked in {_ldd_mapping_dir} and {_script_dir})")
        if missing:
            raise SystemExit(
                f"--sample {args.sample} requires these to exist but they are missing: "
                + "; ".join(missing)
            )

        if args.rename and not args.rename_v:
            args.rename_v = _rt
            print(f"[--sample {args.sample}] auto-set --rename_v={_rt!r}")
        if args.view and not args.view_v:
            args.view_v = _rv if args.rename else _ov
            print(f"[--sample {args.sample}] auto-set --view_v={args.view_v!r}")

    # ----- model init -----
    global CHAT, client
    is_gemini = args.model.startswith("gemini")
    if is_gemini:
        ensure_gemini()
        # Under gemini, stage 1 also routes through gemini — no openai needed.
    else:
        ensure_openai()

    dev_df = pd.read_csv(args.csv_path)
    dev_df = apply_row_selection(dev_df, args.rows)
    print(f"📄 Running on {len(dev_df)} rows from {args.csv_path} (dataset={args.dataset}, model={args.model})")

    # ----- dataset-specific table/view lists -----
    ds = DATASET_TABLES[args.dataset]
    ds_org_tables = ds["org_tables"]
    ds_db_dict = ds["db_dict"]
    base_tables = ds["renamed_tables"] if args.rename else ds["org_tables"]
    extra_views_pool = ds["renamed_views"] if args.rename else ds["org_views"]

    # ----- --rename_v override (tables + views pool) -----
    # rename_v variable name convention: "{dataset}_renamed_tables[_<suffix>]".
    # When matched:
    #   - default mapping file → "name_mapping_{dataset}[_<suffix>].json"
    #   - default views pool   → globals()["{dataset}_renamed_views[_<suffix>]"] (empty if missing)
    _rename_v_suffix = None
    if args.rename and args.rename_v:
        _custom = globals().get(args.rename_v)
        if _custom is None:
            raise SystemExit(
                f"--rename_v {args.rename_v!r} not found as a module-level variable in run_spider_din.py."
            )
        if not isinstance(_custom, list) or not all(isinstance(t, str) for t in _custom):
            raise SystemExit(
                f"--rename_v {args.rename_v!r} must be a list of strings; got {type(_custom).__name__}."
            )
        print(f"📝 --rename_v: overriding renamed_tables with {args.rename_v!r} ({len(_custom)} tables)")
        base_tables = _custom

        import re as _re_rv
        _m = _re_rv.match(r"^(spider|bird)_renamed_tables(?:_(\w+))?$", args.rename_v)
        if _m:
            _rename_v_suffix = _m.group(2)
            _views_var = args.rename_v.replace("_renamed_tables", "_renamed_views")
            _custom_views = globals().get(_views_var)
            if _custom_views is None:
                print(f"⚠️  --rename_v: no views list {_views_var!r} defined — views pool is empty")
                extra_views_pool = []
            else:
                if not isinstance(_custom_views, list) or not all(isinstance(v, str) for v in _custom_views):
                    raise SystemExit(
                        f"{_views_var!r} must be a list of strings; got {type(_custom_views).__name__}."
                    )
                print(f"📝 --rename_v: using views pool {_views_var!r} ({len(_custom_views)} views)")
                extra_views_pool = _custom_views
        else:
            print(f"⚠️  --rename_v {args.rename_v!r} does not match '{{dataset}}_renamed_tables[_<suffix>]' — "
                  f"views pool and mapping file fall back to dataset defaults.")

    # ----- --view_v explicit views-pool override (wins over --rename_v auto-derivation) -----
    _view_v_suffix = None
    if args.view_v:
        _custom_views_v = globals().get(args.view_v)
        if _custom_views_v is None:
            raise SystemExit(
                f"--view_v {args.view_v!r} not found as a module-level variable in run_spider_din.py."
            )
        if not isinstance(_custom_views_v, list) or not all(isinstance(v, str) for v in _custom_views_v):
            raise SystemExit(
                f"--view_v {args.view_v!r} must be a list of strings; got {type(_custom_views_v).__name__}."
            )
        print(f"📝 --view_v: overriding views pool with {args.view_v!r} ({len(_custom_views_v)} views)")
        extra_views_pool = _custom_views_v
        import re as _re_vv
        _m_vv = _re_vv.match(r".+_(\d+)$", args.view_v)
        if _m_vv:
            _view_v_suffix = _m_vv.group(1)

    # ----- --per_db validation -----
    if args.per_db:
        if not ds_db_dict:
            raise SystemExit(
                f"--per_db requires DATASET_TABLES['{args.dataset}']['db_dict'] to be populated. "
                f"Currently empty for dataset={args.dataset!r}."
            )
        if "db_id" not in dev_df.columns:
            raise SystemExit("--per_db requires a 'db_id' column in the input CSV.")

    # History CSV column names (rename-aware; match run_spider.py)
    # History CSV column names (rename-aware; honor --rename_v suffix).
    # With --rename_v bird_renamed_tables_50 the renamed-history columns carry a
    # matching _<suffix> (e.g. "renamed_SQL_50"); they must exist in the sample CSV.
    if args.rename:
        _tail = f"_{_rename_v_suffix}" if _rename_v_suffix else ""
        hist_sql_col       = f"renamed_SQL{_tail}"
        hist_view_sql_col  = f"renamed_view_SQL{_tail}"
        hist_gt_tables_col = f"gt_renamed_tables{_tail}"
    else:
        hist_sql_col       = "SQL"
        hist_view_sql_col  = "view_SQL"
        hist_gt_tables_col = "gt_tables"
    TOP_K = 3

    # ----- base schema -----
    print(f"📚 Building base schema from {len(base_tables)} tables...")
    _present = {n.lower() for n in list_tables_and_views(db_path)}
    _missing = [t for t in base_tables if t.lower() not in _present]
    if _missing:
        print(f"⚠️  {len(_missing)}/{len(base_tables)} base tables NOT found in {db_path}: {_missing}")

    # Per user: --rename → get_database_schema (renamed_tables are views); else → generate_schema_prompt.
    # Some views may have DATE columns storing ints (e.g. YYYYMMDD as 19800930) that trip
    # SQLAlchemy's fromisoformat coercion. Call per-table; on TypeError, fall back to
    # get_database_schema_manual which produces the SAME output format via a raw sqlite
    # cursor (no type coercion) so the LLM still sees consistent CREATE TABLE + sample rows.
    if args.rename:
        pieces = []
        rescued = []
        for t in base_tables:
            try:
                pieces.append(get_database_schema(db_path, [t], sample_rows=3, include_views=True))
            except TypeError:
                pieces.append(get_database_schema_manual(db_path, [t], sample_rows=3))
                rescued.append(t)
        if rescued:
            print(f"⚠️  {len(rescued)} rename views fell back to get_database_schema_manual "
                  f"(date-coercion): {rescued}")
        base_schema = "\n\n".join(pieces) + "\n\n"
    else:
        pieces = []
        for i, t in enumerate(base_tables):
            print(f"  [{i+1}/{len(base_tables)}] {t}", end="\r")
            pieces.append(generate_schema_prompt(db_path=db_path, num_rows=3, no_join=False, target_table=t))
        print()  # clear the \r line
        base_schema = "\n\n".join(pieces) + "\n\n"

    # ----- FK injection for --rename -----
    _org_keyed = (args.dataset == "bird")
    mapping_path = None
    if args.rename:
        script_dir = os.path.dirname(os.path.abspath(__file__))              # .../benchmarks/spider_data/
        # Mapping files live at <LDD_ROOT>/mapping_files (two levels up); legacy fallback is script_dir.
        _ldd_mapping_dir = os.path.abspath(os.path.join(script_dir, "..", "..", "mapping_files"))
        _default_mapping = f"name_mapping_{args.dataset}"
        if _rename_v_suffix:
            _default_mapping += f"_{_rename_v_suffix}"
        _default_mapping += ".json"

        if args.mapping_path:
            mapping_path = args.mapping_path
        else:
            _ldd_candidate    = os.path.join(_ldd_mapping_dir, _default_mapping)
            _legacy_candidate = os.path.join(script_dir, _default_mapping)
            if os.path.exists(_ldd_candidate):
                mapping_path = _ldd_candidate
            elif os.path.exists(_legacy_candidate):
                mapping_path = _legacy_candidate
            else:
                mapping_path = _ldd_candidate  # report the primary-default path in the error below
        if not os.path.exists(mapping_path):
            raise SystemExit(
                f"--rename needs a mapping file but {mapping_path} does not exist. "
                f"Pass --mapping_path explicitly."
            )
        fk_block = build_renamed_fk_block(db_path, ds_org_tables, mapping_path,
                                          org_keyed_columns=_org_keyed)
        if fk_block:
            base_schema += fk_block
            print(f"🔗 Injected {fk_block.count(chr(10)) - 2} renamed FK lines into base_schema")
        else:
            print("⚠️  No FKs translated to renamed namespace — base_schema unchanged.")

    # ----- history-derived structures -----
    sample = None
    exact_clusters = None
    question_cluster_map = None
    ref_texts = None
    ref_embs = None

    if args.history_path:
        sample, exact_clusters, question_cluster_map = build_clusters_from_history(
            args.history_path, sql_col=hist_sql_col, gt_tables_col=hist_gt_tables_col,
            sample_pct=args.sample,
        )
        print("🧠 Loading BGE encoder and building reference embeddings from history...")
        ensure_bge_model()
        ref_texts, ref_embs = prepare_reference_embeddings(list(sample['question']))

    # ---------------- --per_db setup (lazy cache) ----------------
    # Per-db resources: (base_schema, extra_views_pool, exact_clusters, sample, ref_texts, ref_embs)
    per_db_cache = {}
    _per_db_warned = set()
    _db_tables_active = {}  # db_id -> tables in active namespace (renamed if --rename else org)

    if args.per_db:
        if args.rename:
            # Reuse the mapping_path already resolved above (honors --mapping_path and --rename_v).
            _table_to_view, _ = load_rename_mapping(mapping_path, org_keyed_columns=_org_keyed)
            for db_id, tables in ds_db_dict.items():
                mapped = []
                for t in tables:
                    rn = _table_to_view.get(t.lower())
                    if rn:
                        mapped.append(rn)
                    else:
                        print(f"⚠️  --per_db --rename: db_id={db_id!r} table {t!r} has no rename mapping, skipping")
                _db_tables_active[db_id] = mapped
        else:
            _db_tables_active = {k: list(v) for k, v in ds_db_dict.items()}
        print(f"📦 --per_db active with {len(_db_tables_active)} db_ids")

    def resolve_per_db(db_id):
        """Return (base_schema, extra_views_pool, exact_clusters, sample, ref_texts, ref_embs)
        for this db_id — cached; falls back to globals on unknown db_id."""
        if not args.per_db or db_id is None or db_id not in _db_tables_active:
            if args.per_db and db_id is not None and db_id not in _db_tables_active and db_id not in _per_db_warned:
                print(f"⚠️  --per_db: db_id={db_id!r} not in db_dict, falling back to full union for this question")
                _per_db_warned.add(db_id)
            return base_schema, extra_views_pool, exact_clusters, sample, ref_texts, ref_embs

        if db_id in per_db_cache:
            return per_db_cache[db_id]

        db_tables = _db_tables_active[db_id]
        db_tables_lower = {t.lower() for t in db_tables}
        print(f"🔧 --per_db: building resources for db_id={db_id!r} ({len(db_tables)} tables)")

        # --- base schema: per-table, with --rename fallback to manual reader ---
        pieces = []
        rescued = []
        for t in db_tables:
            if args.rename:
                try:
                    pieces.append(get_database_schema(db_path, [t], sample_rows=3, include_views=True))
                except TypeError:
                    pieces.append(get_database_schema_manual(db_path, [t], sample_rows=3))
                    rescued.append(t)
            else:
                try:
                    pieces.append(generate_schema_prompt(
                        db_path=db_path, num_rows=3, no_join=False, target_table=t
                    ))
                except Exception as _e:
                    logging.warning(f"generate_schema_prompt failed for {t!r}: {_e}")
        _bs = "\n\n".join(p for p in pieces if p) + "\n\n"

        # --- FK block for --rename ---
        if args.rename:
            # Reuse the already-resolved mapping_path from the main --rename block above
            # (which prefers Logical-Database-Design/mapping_files, falls back to script dir).
            _fk = build_renamed_fk_block(
                db_path, ds_db_dict[db_id], mapping_path,
                org_keyed_columns=_org_keyed,
            )
            if _fk:
                _bs += _fk

        # --- views pool: only views whose all base tables lie in db_tables ---
        _vp = []
        if extra_views_pool:
            for v in extra_views_pool:
                bases = parse_view_base_tables(v)
                if bases and all(b.lower() in db_tables_lower for b in bases):
                    _vp.append(v)

        # --- clusters: only those whose tables ⊆ db_tables ---
        _ec = None
        if exact_clusters is not None:
            _ec = [
                c for c in exact_clusters
                if all(t.lower() in db_tables_lower for t in c["tables"])
            ]

        # --- history sample subset + per-db BGE embeddings ---
        _sp = None
        _rt = None
        _re = None
        if sample is not None and "db_id" in sample.columns:
            _sp = sample[sample["db_id"] == db_id].reset_index(drop=True)
            if len(_sp) > 0:
                _rt, _re = prepare_reference_embeddings(list(_sp["question"]))

        per_db_cache[db_id] = (_bs, _vp, _ec, _sp, _rt, _re)
        return per_db_cache[db_id]

    # ----- log/output suffix and folder -----
    suffix = ""
    if args.rename:
        suffix += "_rename"
    if args.view:
        suffix += "_withview"
    if args.cluster:
        suffix += "_clusterfilter" if args.cluster_filter else "_cluster"
    if args.history_path:
        suffix += f"_history{args.sample}" if args.sample < 100 else "_history"
    if args.use_linking:
        if args.view_adhoc:
            suffix += "_adhoclinking"
        elif args.view_relink:
            suffix += "_relinking"
        else:
            suffix += "_uselinking"
    if args.per_db:
        # _top3 only when TOP_K history retrieval is actually in use.
        suffix += "_perdb_top3" if args.history_path else "_perdb"
    # Append rename_v / view_v level marker for non-history runs (history already encodes
    # it via _history{N}). Avoids collision when 50% and 100% variants share other flags.
    if not args.history_path:
        _level = _rename_v_suffix or _view_v_suffix
        if _level:
            suffix += f"_{_level}"
    # Model suffix: extract digits from model name → e.g. "gpt-4.1-mini" → "gpt41",
    # "gemini-2.5-flash-lite" → "gem25", "gpt-5.4-mini" → "gpt54"
    import re as _re
    _model_digits = "".join(_re.findall(r"\d", args.model))
    if is_gemini:
        suffix += f"_gem{_model_digits}"
    elif args.model != "gpt-4.1-mini":
        suffix += f"_gpt{_model_digits}"

    run_id = time.strftime("%Y%m%d-%H%M%S")
    log_base = f"logs_din_{args.dataset}" if args.dataset != "spider" else "logs_din"
    log_dir = os.path.join(log_base, f"run_{run_id}{suffix}")
    os.makedirs(log_dir, exist_ok=True)
    print(f"📂 Logging prompts to: {log_dir}")

    # Output column names (dinsql_ prefix)
    linking_col = f"dinsql_linking{suffix}"
    label_col = f"dinsql_label{suffix}"
    subq_col = f"dinsql_sub_questions{suffix}"
    sql_col_out = f"dinsql_sql{suffix}"
    revised_sql_col_out = f"dinsql_revised_sql{suffix}"

    # Pre-build non_nested / nested prompts (flag-dependent template picked once)
    non_nested_prompt = make_non_nested_prompt(args.rename, args.view)
    nested_prompt = make_nested_prompt(args.rename, args.view)

    failed_idx = []

    # --view_adhoc: cache successful views keyed by frozenset(lowered table names).
    # Failures are NOT cached so each question can retry past LLM flakiness.
    adhoc_view_cache = {}

    for index, row in dev_df.iterrows():
        log_file = os.path.join(log_dir, f"q{int(index):04d}.log")
        # Resolve per-db resources for this question (no-op if --per_db off)
        _q_db_id = row.get("db_id") if "db_id" in dev_df.columns else None
        _q_bs, _q_vp, _q_ec, _q_sp, _q_rt, _q_re = resolve_per_db(_q_db_id)
        for attempt in range(3):
            try:
                # Clear log for this attempt so a successful retry replaces partial output
                open(log_file, "w", encoding="utf-8").close()
                question = row["question"]
                append_log(log_dir, index, "QUESTION", str(question))

                # ---- Stage 0 (when --view_adhoc or --view_relink): parse tables from --use_linking ----
                adhoc_view_name = None
                adhoc_view_schema_str = None
                adhoc_skip_stage1 = False
                relink_matched_views_schema = None
                relink_skip_stage1 = False
                stage0_tables = []
                if args.view_adhoc or args.view_relink:
                    stage0_value = row[args.use_linking]
                    mode_label = "adhoc view" if args.view_adhoc else "relink"
                    append_log(log_dir, index, f"STAGE 0: {mode_label} seed (from --use_linking)",
                               f"column={args.use_linking}\nvalue={stage0_value}")
                    try:
                        stage0_tables_lower = set(parse_retrieved_tables_from_links(stage0_value))
                    except Exception:
                        stage0_tables_lower = set()
                    bt_lookup = {t.lower(): t for t in base_tables}
                    stage0_tables = [bt_lookup[t] for t in stage0_tables_lower if t in bt_lookup]

                    tag = "adhoc view" if args.view_adhoc else "relink"
                    print(f"[{tag}] q{int(index):04d}: stage-0 linked tables "
                          f"({len(stage0_tables)}): {stage0_tables}")

                if args.view_adhoc:
                    if len(stage0_tables) >= 2:
                        cache_key = frozenset(t.lower() for t in stage0_tables)
                        if cache_key in adhoc_view_cache:
                            adhoc_view_name, adhoc_view_schema_str = adhoc_view_cache[cache_key]
                            print(f"[adhoc view] q{int(index):04d}: 🎯 cache HIT → {adhoc_view_name!r}")
                            append_log(log_dir, index,
                                       f"STAGE 0: adhoc view cache HIT ({adhoc_view_name})",
                                       adhoc_view_schema_str or "")
                        else:
                            print(f"[adhoc view] q{int(index):04d}: cache MISS → discovering FKs")
                            fk_conds = find_fk_conditions_for_view_adhoc(
                                db_path, stage0_tables,
                                rename_mode=args.rename,
                                mapping_path=mapping_path,
                                ds_org_tables=ds_org_tables,
                                org_keyed=_org_keyed,
                            )
                            if fk_conds:
                                adhoc_view_name, adhoc_view_schema_str = create_adhoc_view(
                                    db_path, stage0_tables, fk_conds,
                                    model=args.model, is_gemini=is_gemini,
                                    excluded_views=(list(ds.get("org_views", []))
                                                    + list(ds.get("renamed_views", []))),
                                )
                                if adhoc_view_name:
                                    adhoc_view_cache[cache_key] = (adhoc_view_name, adhoc_view_schema_str)
                                    append_log(log_dir, index,
                                               f"STAGE 0: adhoc view created ({adhoc_view_name})",
                                               adhoc_view_schema_str)
                                else:
                                    append_log(log_dir, index,
                                               "STAGE 0: adhoc view FAILED (LLM) — stage-1 uses base schema",
                                               f"tables={stage0_tables}\nfk_conditions={fk_conds}")
                            else:
                                print(f"[adhoc view] q{int(index):04d}: ⚠️  no FKs among "
                                      f"{stage0_tables} → fall back to base schema")
                                append_log(log_dir, index,
                                           "STAGE 0: no FK conditions found — stage-1 uses base schema",
                                           f"tables={stage0_tables}")
                    else:
                        adhoc_skip_stage1 = True
                        print(f"[adhoc view] q{int(index):04d}: ⚠️  only {len(stage0_tables)} "
                              f"linked table(s) → SKIPPING stage 1, reusing --use_linking value")
                        append_log(log_dir, index,
                                   "STAGE 0: <2 linked tables — stage-1 SKIPPED, reusing --use_linking value",
                                   f"tables={stage0_tables}")

                if args.view_relink:
                    if len(stage0_tables) >= 2:
                        if _q_vp:
                            matched_views_s0 = find_matching_views(_q_vp, stage0_tables)
                        else:
                            matched_views_s0 = []
                        if matched_views_s0:
                            relink_matched_views_schema = "\n\n".join(
                                generate_schema_prompt(db_path=db_path, num_rows=3, no_join=False, target_table=v)
                                for v in matched_views_s0
                            )
                            print(f"[relink] q{int(index):04d}: matched {len(matched_views_s0)} view(s) "
                                  f"from stage-0 tables → {matched_views_s0}")
                            append_log(log_dir, index,
                                       f"STAGE 0: relink matched {len(matched_views_s0)} view(s)",
                                       f"views={matched_views_s0}")
                        else:
                            relink_skip_stage1 = True
                            print(f"[relink] q{int(index):04d}: no views matched stage-0 tables "
                                  f"→ SKIPPING stage 1, reusing --use_linking value")
                            append_log(log_dir, index,
                                       "STAGE 0: relink — no matching views — stage-1 SKIPPED, "
                                       "reusing --use_linking value",
                                       f"tables={stage0_tables}")
                    else:
                        relink_skip_stage1 = True
                        print(f"[relink] q{int(index):04d}: ⚠️  only {len(stage0_tables)} "
                              f"linked table(s) → SKIPPING stage 1, reusing --use_linking value")
                        append_log(log_dir, index,
                                   "STAGE 0: <2 linked tables — stage-1 SKIPPED, reusing --use_linking value",
                                   f"tables={stage0_tables}")

                # Stage-1 input schema: base + (adhoc view | relink matched views) when applicable.
                stage1_input_schema = _q_bs
                if args.view_adhoc and adhoc_view_schema_str:
                    stage1_input_schema = _q_bs + "\n\n" + adhoc_view_schema_str + "\n\n"
                elif args.view_relink and relink_matched_views_schema:
                    stage1_input_schema = _q_bs + "\n\n" + relink_matched_views_schema + "\n\n"

                # ---- Stage 1: schema linking ----
                skip_stage1 = args.use_linking and (
                    (not args.view_adhoc and not args.view_relink)
                    or adhoc_skip_stage1
                    or relink_skip_stage1
                )
                if skip_stage1:
                    schema_links = row[args.use_linking]
                    if args.view_adhoc:
                        reason = "<2 linked tables under --view_adhoc"
                    elif args.view_relink:
                        reason = ("no view to justify re-linking under --view_relink "
                                  "(<2 tables or no matching views)")
                    else:
                        reason = "read from column"
                    append_log(log_dir, index, f"STAGE 1: linking (skipped — {reason})",
                               f"column={args.use_linking}\nvalue={schema_links}")
                else:
                    linking_prompt_text = schema_linking_prompt.format(
                        question=question, schema=stage1_input_schema
                    )
                    # Under gemini, route stage 1 through gemini (structured output).
                    # Otherwise stay on LangChain + GPT-4.1-mini.
                    # If the LLM call OR parse fails AND --use_linking is set, fall back to
                    # the pre-computed linking column instead of re-raising (recovers gemini
                    # repetition-loop failures without triggering the attempt-level retry).
                    try:
                        if is_gemini:
                            append_log(log_dir, index, "STAGE 1 PROMPT: schema linking (gemini)",
                                       linking_prompt_text)
                            linking_response = chat_with_gemini_DIN(
                                linking_prompt_text, model=args.model,
                                response_fields={"schema_links": list},
                            )
                        else:
                            append_log(log_dir, index, "STAGE 1 PROMPT: schema linking", linking_prompt_text)
                            linking_chain = LLMChain(llm=CHAT, prompt=schema_linking_prompt)
                            linking_response = linking_chain.run(question=question, schema=stage1_input_schema)
                        append_log(log_dir, index, "STAGE 1 RESPONSE", linking_response)
                        _cleaned = re.sub(r'//.*', '', linking_response.replace("```json", "").replace("```", ""))
                        try:
                            schema_links = ast.literal_eval(_cleaned)['schema_links']
                        except (SyntaxError, ValueError):
                            # Wrap bare backtick identifiers like `x`.`y` -> "`x`.`y`" so ast.literal_eval succeeds.
                            _fixed = re.sub(r'([\[,]\s*)(`[^`]+`(?:\.`[^`]+`)*)', r'\1"\2"', _cleaned)
                            schema_links = ast.literal_eval(_fixed)['schema_links']
                        schema_links = str(schema_links)
                        dev_df.at[index, linking_col] = schema_links
                    except Exception as _stage1_err:
                        if args.use_linking:
                            schema_links = row[args.use_linking]
                            print(f"[stage 1] q{int(index):04d}: fresh linking FAILED "
                                  f"({type(_stage1_err).__name__}: {_stage1_err}) — "
                                  f"falling back to --use_linking column")
                            append_log(log_dir, index,
                                       "STAGE 1 FAILED — falling back to --use_linking",
                                       f"error={type(_stage1_err).__name__}: {_stage1_err}\n"
                                       f"fallback column={args.use_linking}\nvalue={schema_links}")
                            schema_links = str(schema_links)
                            dev_df.at[index, linking_col] = schema_links
                        else:
                            raise

                # ---- Parse schema_links → retrieved_tables (needed by --view and --cluster) ----
                retrieved_tables = []
                if args.view or args.cluster:
                    try:
                        retrieved_tables = parse_retrieved_tables_from_links(schema_links)
                    except Exception as e:
                        logging.warning(f"idx {index}: failed to parse schema_links: {e}")

                # ---- Cluster lookup (only --cluster needs it) ----
                cluster_res = None
                if args.cluster and _q_ec is not None and retrieved_tables:
                    cluster_res = find_all_clusters_for_tables(
                        retrieved_tables, _q_ec, sqlite_path=db_path
                    )

                # ---- Cluster filter: optionally restrict stage-2/3/4 base schema + FKs + views ----
                apply_cluster_filter = False
                effective_base = None
                cluster_set_lc = None
                if args.cluster_filter and cluster_res is not None and cluster_res.get("tables"):
                    _cluster_tables = cluster_res["tables"]
                    _bt_lookup = {t.lower(): t for t in base_tables}
                    cluster_tables_oc = [_bt_lookup.get(t.lower(), t) for t in _cluster_tables]
                    cluster_set_lc = {t.lower() for t in cluster_tables_oc}

                    effective_base = "\n\n".join(
                        generate_schema_prompt(db_path=db_path, num_rows=3, no_join=False, target_table=t)
                        for t in cluster_tables_oc
                    ) + "\n\n"

                    _fk_lines = find_fk_conditions_for_view_adhoc(
                        db_path, cluster_tables_oc,
                        rename_mode=args.rename,
                        mapping_path=mapping_path,
                        ds_org_tables=ds_org_tables,
                        org_keyed=_org_keyed,
                    )
                    if _fk_lines:
                        effective_base += "Foreign Keys:\n" + "\n".join(
                            fk.replace("=", " = ") for fk in _fk_lines
                        ) + "\n\n"

                    apply_cluster_filter = True
                    append_log(log_dir, index,
                               "CLUSTER FILTER: restricted schema to cluster tables",
                               f"tables ({len(cluster_tables_oc)}): {cluster_tables_oc}\n"
                               f"fks ({len(_fk_lines)}): {_fk_lines}")
                elif args.cluster_filter:
                    append_log(log_dir, index,
                               "CLUSTER FILTER: no matched clusters — falling back to full schema",
                               "")

                # ---- Build updated_schema (inject views matching Stage-1 tables) ----
                if args.view_adhoc:
                    if apply_cluster_filter:
                        updated_schema = effective_base
                        if (adhoc_view_schema_str and stage0_tables
                                and all(t.lower() in cluster_set_lc for t in stage0_tables)):
                            updated_schema += adhoc_view_schema_str + "\n\n"
                    else:
                        updated_schema = stage1_input_schema
                elif args.view_relink:
                    if apply_cluster_filter:
                        updated_schema = effective_base
                        if args.view and _q_vp and retrieved_tables:
                            matched_views = find_matching_views(_q_vp, retrieved_tables)
                            matched_views = [
                                v for v in matched_views
                                if all(b.lower() in cluster_set_lc for b in parse_view_base_tables(v))
                            ]
                            if matched_views:
                                updated_schema += "\n\n" + "\n\n".join(
                                    generate_schema_prompt(db_path=db_path, num_rows=3, no_join=False, target_table=v)
                                    for v in matched_views
                                ) + "\n\n"
                    else:
                        updated_schema = stage1_input_schema
                else:
                    updated_schema = effective_base if apply_cluster_filter else _q_bs
                    if args.view and _q_vp and retrieved_tables:
                        matched_views = find_matching_views(_q_vp, retrieved_tables)
                        if apply_cluster_filter:
                            matched_views = [
                                v for v in matched_views
                                if all(b.lower() in cluster_set_lc for b in parse_view_base_tables(v))
                            ]
                        if matched_views:
                            updated_schema += "\n\n" + "\n\n".join(
                                generate_schema_prompt(db_path=db_path, num_rows=3, no_join=False, target_table=v)
                                for v in matched_views
                            ) + "\n\n"

                # ---- Top-K history SQL retrieval (--history_path) ----
                top_sqls = ""
                if args.history_path and _q_rt is not None and _q_sp is not None and len(_q_sp) > 0:
                    # Choose retrieval pool: filtered by clusters (--cluster) or the per-db (or global) sample.
                    if args.cluster and cluster_res is not None and cluster_res.get('indices'):
                        cand_indices = cluster_res['indices']
                        src_df = _q_sp if _q_sp is not None else sample
                        valid = [i for i in cand_indices if i in src_df.index]
                        if valid:
                            cand_questions = src_df.loc[valid, 'question'].astype(str).to_list()
                            local_refs, local_embs = prepare_reference_embeddings(
                                cand_questions, indices=valid
                            )
                            top_results = topk_embedding_cosine_sim(
                                question, local_refs, local_embs, top_k=TOP_K
                            )
                        else:
                            top_results = []
                        # Top-up from per-db (or global) pool when the cluster pool yielded
                        # fewer than TOP_K — preserves cluster picks first, then adds the
                        # next-best questions from the same db without duplicating indices.
                        if len(top_results) < TOP_K:
                            already = {r[0] for r in top_results}
                            extras_needed = TOP_K - len(top_results)
                            backup = topk_embedding_cosine_sim(
                                question, _q_rt, _q_re, top_k=TOP_K + len(already)
                            )
                            extras = [r for r in backup if r[0] not in already][:extras_needed]
                            top_results = list(top_results) + extras
                    else:
                        top_results = topk_embedding_cosine_sim(
                            question, _q_rt, _q_re, top_k=TOP_K
                        )
                    top_indices = [x[0] for x in top_results]
                    top_sqls = " \n".join(
                        _q_sp.loc[top_indices, hist_sql_col].astype(str).to_list()
                    )
                    if args.view:
                        top_sqls += " \n" + " \n".join(
                            _q_sp.loc[top_indices, hist_view_sql_col].astype(str).to_list()
                        )

                # ---- Cluster join paths (--cluster) ----
                paths_str = ""
                if args.cluster and cluster_res is not None:
                    paths_str = ', \n'.join(sorted(set(cluster_res.get('paths', []))))

                # Conditional injection blocks — headers only when content exists
                history_block = f"History SQLs:\n{top_sqls}\n\n" if top_sqls else ""
                paths_block = f"Common Join Paths:\n{paths_str}\n\n" if paths_str else ""

                # ---- Stage 2: classification ----
                class_prompt_text = classification_prompt.format(
                    question=question,
                    schema=updated_schema,
                    schema_links=schema_links,
                    history_block=history_block,
                    paths_block=paths_block,
                )
                append_log(log_dir, index, "STAGE 2 PROMPT: classification", class_prompt_text)
                if is_gemini:
                    class_response = chat_with_gemini_DIN(class_prompt_text, model=args.model)
                else:
                    class_response = chat_with_chatgpt_DIN(class_prompt_text, model=args.model)
                append_log(log_dir, index, "STAGE 2 RESPONSE", class_response)
                class_json = json.loads(extract_json_block(class_response))
                label = class_json.get("Label", "NON-NESTED")
                sub_questions = class_json.get("sub-questions", [])
                dev_df.at[index, label_col] = str(label)
                dev_df.at[index, subq_col] = str(sub_questions)
                print(f"[{index}] label={label}")

                # ---- Stage 3: SQL generation (branch on label) ----
                if "EASY" in label:
                    gen_template = easy_prompt
                    gen_kwargs = dict(
                        question=question,
                        schema=updated_schema,
                        schema_links=schema_links,
                        history_block=history_block,
                        paths_block=paths_block,
                    )
                elif "NON-NESTED" in label:
                    gen_template = non_nested_prompt
                    gen_kwargs = dict(
                        question=question,
                        schema=updated_schema,
                        schema_links=schema_links,
                        history_block=history_block,
                        paths_block=paths_block,
                    )
                else:
                    gen_template = nested_prompt
                    gen_kwargs = dict(
                        question=question,
                        schema=updated_schema,
                        schema_links=schema_links,
                        sub_questions=sub_questions,
                        history_block=history_block,
                        paths_block=paths_block,
                    )
                gen_prompt_text = gen_template.format(**gen_kwargs)
                append_log(log_dir, index, f"STAGE 3 PROMPT: SQL generation ({label})", gen_prompt_text)
                if is_gemini:
                    gen_response = chat_with_gemini_DIN(gen_prompt_text, model=args.model, response_fields={"SQL": str})
                    sql_query = json.loads(gen_response)["SQL"]
                else:
                    gen_response = chat_with_chatgpt_DIN(gen_prompt_text, model=args.model)
                    sql_query = json.loads(extract_json_block(gen_response))["SQL"].replace("```sql", "").replace("```", "")
                append_log(log_dir, index, "STAGE 3 RESPONSE", gen_response)
                dev_df.at[index, sql_col_out] = sql_query
                print(f"[{index}] sql: {sql_query}")

                # ---- Stage 4: self-correction (no execution between 3 and 4) ----
                corr_prompt_text = correction_prompt.format(
                    question=question,
                    schema=updated_schema,
                    sql_query=sql_query,
                    history_block=history_block,
                    paths_block=paths_block,
                )
                append_log(log_dir, index, "STAGE 4 PROMPT: self-correction", corr_prompt_text)
                if is_gemini:
                    corr_response = chat_with_gemini_DIN(corr_prompt_text, model=args.model, response_fields={"Revised_SQL": str})
                else:
                    corr_response = chat_with_chatgpt_DIN(corr_prompt_text, model=args.model)
                append_log(log_dir, index, "STAGE 4 RESPONSE", corr_response)
                try:
                    if is_gemini:
                        revised_sql = json.loads(corr_response)["Revised_SQL"]
                    else:
                        revised_sql = json.loads(extract_json_block(corr_response))["Revised_SQL"].replace("```sql", "").replace("```", "")
                except Exception as e:
                    logging.error(f"idx {index}: error parsing correction response: {e}")
                    revised_sql = sql_query
                one_liner = (revised_sql or sql_query or "SELECT * FROM table").replace('\n', ' ').replace('\r', ' ')
                dev_df.at[index, revised_sql_col_out] = one_liner
                append_log(log_dir, index, "FINAL revised_sql", one_liner)
                print(f"[{index}] revised: {one_liner}")
                break

            except Exception as e:
                print(f"Attempt {attempt+1} failed for index {index}: {e}")
                if attempt < 2:
                    time.sleep(1 * (attempt + 1))
                else:
                    failed_idx.append(index)
                    print(f"❌ Giving up after 3 attempts on index {index}")

        # Incremental save every 100 rows (crash resilience)
        if (list(dev_df.index).index(index) + 1) % 100 == 0:
            _inc_path = os.path.join(log_dir, f"{os.path.splitext(os.path.basename(args.csv_path))[0]}{suffix}_dinsql_out.csv")
            dev_df.to_csv(_inc_path, index=False)
            print(f"💾 Incremental save at row {index}")

    base_name = os.path.splitext(os.path.basename(args.csv_path))[0]
    out_path = os.path.join(log_dir, f"{base_name}{suffix}_dinsql_out.csv")
    dev_df.to_csv(out_path, index=False)
    print(f"💾 Saved results to: {out_path}")
    print(f"Failed indices: {failed_idx}")


if __name__ == "__main__":
    main()