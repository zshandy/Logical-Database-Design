"""Prompt templates used by the BaseSQL pipeline.

Three stage templates:
  - Stage 1 schema linking (with and without view example), plus the human shell
  - Stage 2 SQL generation
  - Stage 3 SQL revision

The stage-2/3 templates are formatted with f-string substitution; placeholders
must be left as ``{xxx}`` in the body and filled by ``build_gen_prompt`` /
``build_revise_prompt``.
"""

from __future__ import annotations


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
Question: Which year has the least number of movies that was released and what is the title of the movie in that year that has the highest number of rating score of 1?
Please respond with a JSON object structured as follows:
{{
    "chain_of_thought_reasoning": "Let’s think step by step. In the question , we are asked: "Which year" so we need column = [movies.movie_release_year]
"number of movies" so we need column = [movies.movie_id]
"title of the movie" so we need column = [movies.movie_title]
"rating score" so we need column = [ratings.rating_score]
Based on the columns and tables, we need these Foreign_keys = [movies.movie_id = ratings.movie_id].
Based on the tables, columns, and Foreign_keys, The set of possible cell values are = [1]",
    "schema_links": [`movies`.`movie_release_year`, `movies`.`movie_title`, `ratings`.`rating_score`, `movies`.`movie_id=ratings.movie_id`, 1]
}}


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
Question: Among the lists created by user 4208563, which one has the highest number of followers? Indicate how many followers it has and whether the user was a subscriber or not when he created the list.
Please respond with a JSON object structured as follows:
{{
    "chain_of_thought_reasoning": "Let’s think step by step. In the question , we are asked:
"user" so we need column = [lists_users.user_id]
"number of followers" so we need column = [lists.list_followers]
"user was a subscriber or not" so we need column = [lists_users.user_subscriber]
Based on the columns and tables, we need these Foreign_keys = [lists.user_id = lists_user.user_id,lists.list_id = lists_user.list_id].
Based on the tables, columns, and Foreign_keys, The set of possible cell values are = [1, 4208563]",
    "schema_links": [`lists`.`list_followers`,`lists_users`.`user_subscriber`,`lists`.`user_id = lists_users`.`user_id`,`lists`.`list_id = lists_users`.`list_id`,`lists_users`.`user_id`, 4208563, 1]
}}"""


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


SYSTEM_SCHEMA_LINKING_TEMPLATE_JOIN = """
You are an agent designed to find the schema_links for generating SQL queries for each question based on the database schema and Foreign keys.
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

Question: Which year has the least number of movies that was released and what is the title of the movie in that year that has the highest number of rating score of 1?
Please respond with a JSON object structured as follows:
{{
    "chain_of_thought_reasoning": "Let’s think step by step. In the question , we are asked:
Based on the columns and tables, we need to join movies and ratings, so we can use the table that is the joined result of movies and ratings tables: movies_join_ratings.
Since we are using the joined table, there is no need for foreign keys, and columns should come from that table as well.
"Which year" so we need column = [movies_join_ratings.movie_release_year]
"number of movies" so we need column = [movies_join_ratings.movies_movie_id]
"title of the movie" so we need column = [movies_join_ratings.movie_title]
"rating score" so we need column = [movies_join_ratings.rating_score]
Based on the tables, columns, and Foreign_keys, The set of possible cell values are = [1]",
    "schema_links": [`movies_join_ratings`.`movie_release_year`, `movies_join_ratings`.`movie_title`, `movies_join_ratings`.`rating_score`, `movies_join_ratings`.`movies_movie_id`, 1]
}}

Question: How many users gave \"Pavee Lackeen: The Traveller Girl\" movie a rating score of 4?
Please respond with a JSON object structured as follows:
{{
    "chain_of_thought_reasoning": "Let’s think step by step. In the question , we are asked:
Based on the columns and tables, we need to join movies and ratings, so we can use the table that is the joined result of movies and ratings tables: movies_join_ratings.
Since we are using the joined table, there is no need for foreign keys, and columns should come from that table as well
"users" so we need column = [movies_join_ratings.user_id]
\"Pavee Lackeen: The Traveller Girl\" movie so we need column = [movies_join_ratings.movie_title]
"rating score" so we need column = [movies_join_ratings.rating_score]
Based on the tables, columns, and Foreign_keys, The set of possible cell values are = [4, \"Pavee Lackeen: The Traveller Girl\"].",
    "schema_links": [`movies_join_ratings`.`user_id`, `movies_join_ratings`.`movie_title`, movies_join_ratings.rating_score, 4, \"Pavee Lackeen: The Traveller Girl\"]
}}"""  # noqa: E501


# ---------------------------------------------------------------------------
# Stage-2 (SQL gen) and Stage-3 (SQL revise) prompt builders
# ---------------------------------------------------------------------------

_GEN_HISTORY_INSTRUCTIONS = (
    "        12. Make use of the history SQL, it can provide very useful informations such as common joins, common selections and common projections.\n"
    "        13. The history SQLs can be very similar to the actual answer, so make use of them, you should try to make small changes to them to get the desired SQL.\n"
    "        14. Priority should be given to columns that have been explicitly matched with examples relevant to the question's context.\n"
)

_REVISE_HISTORY_INSTRUCTIONS = (
    "        14. Make use of the history SQL, it can provide very useful informations such as common joins, common selections and common projections.\n"
    "        15. The history SQLs can be very similar to the actual answer, so make use of them, you should try to make small changes to them to get the desired SQL.\n"
    "        16. Priority should be given to columns that have been explicitly matched with examples relevant to the question's context.\n"
)


def build_gen_prompt(
    *,
    updated_schema: str,
    question: str,
    schema_links: str,
    history_block: str = "",
    paths_block: str = "",
    dialect: str = "SQLite",
) -> str:
    """Build the stage-2 SQL generation prompt.

    ``dialect`` names the engine the query will actually run against, so the
    model targets the right SQL flavour (BEAVER's splits execute on MySQL).
    """
    history_instructions = _GEN_HISTORY_INSTRUCTIONS if history_block else ""
    return f"""You are a data science expert.
        Below, you are presented with a database schema and a question.
        Your task is to read the schema, understand the question, and generate a valid {dialect} query to answer the question.
        Before generating the final SQL query think step by step on how to write the query.

        Database Schema
        ###
        {updated_schema}

        ###
        This schema offers an in-depth description of the database's architecture, detailing tables, columns, primary keys, foreign keys, and any pertinent information regarding relationships or constraints. Special attention should be given to the examples listed beside each column, as they directly hint at which columns are relevant to our query.

        Database admin instructions:
        1. When you need to find the highest or lowest values based on a certain condition, using ORDER BY + LIMIT 1 is prefered over using MAX/MIN within sub queries.
        2. If predicted query includes an ORDER BY clause to sort the results, you should only include the column(s) used for sorting in the SELECT clause if the question specifically ask for them. Otherwise, omit these columns from the SELECT.
        3. If the question doesn't specify exactly which columns to select, between name column and id column, prefer to select id column.
        4. Make sure you only output the information that is asked in the question. If the question asks for a specific column, make sure to only include that column in the SELECT clause, nothing more.
        5. Predicted query should return all of the information asked in the question without any missing or extra information.
        6. For key phrases mentioned in the question, we have provided the most similar values within the columns denoted by "-- examples" in front of the corresponding column names. This is a crucial hint indicating the correct columns to use for your SQL query.
        7. No matter of how many things the question asks, you should only return one SQL query as the answer having all the information asked in the question, seperated by a comma.
        8. Never use || to concatenate columns in the SELECT. Rather output the columns as they are.
        9. If you are joining multiple tables, make sure to use alias names for the tables and use the alias names to reference the columns in the query. Use T1, T2, T3, ... as alias names.
        10. If you are doing a logical operation on a column, such as mathematical operations and sorting, make sure to filter null values within those columns.
        11. Use ` around table and column names to avoid any confusions.
{history_instructions}
        ###
        Question:
        {question}

        Schema Linking:
        {schema_links}

{history_block}{paths_block}
        Please respond with a JSON object structured as follows:

        {{
            "chain_of_thought_reasoning": "Your thought process on how you arrived at the final SQL query.",
            "SQL": "Your SQL query in a single string."
        }}

        Priority should be given to columns that have been explicitly matched with examples relevant to the question's context.

        Take a deep breath and think step by step to find the correct {dialect} SQL query. If you follow all the instructions and generate the correct query, I will give you 1 million dollars."""


def build_revise_prompt(
    *,
    updated_schema: str,
    question: str,
    schema_links: str,
    sql: str,
    query_status: str,
    query_result,
    history_block: str = "",
    paths_block: str = "",
    dialect: str = "SQLite",
) -> str:
    """Build the stage-3 SQL revision prompt."""
    history_instructions = _REVISE_HISTORY_INSTRUCTIONS if history_block else ""
    return f"""Objective: Your objective is to make sure a query follows the database admin instructions and use the correct conditions.

        Database Schema:
        ###
        {updated_schema}

        ###
        Database admin instructions:
        1. When you need to find the highest or lowest values based on a certain condition, using ORDER BY + LIMIT 1 is prefered over using MAX/MIN within sub queries.
        2. If predicted query includes an ORDER BY clause to sort the results, you should only include the column(s) used for sorting in the SELECT clause if the question specifically ask for them. Otherwise, omit these columns from the SELECT.
        3. If the question doesn't specify exactly which columns to select, between name column and id column, prefer to select id column.
        4. Make sure you only output the information that is asked in the question. If the question asks for a specific column, make sure to only include that column in the SELECT clause, nothing more.
        5. Predicted query should return all of the information asked in the question without any missing or extra information.
        7. For key phrases mentioned in the question, we have provided the most similar values within the columns denoted by "-- examples" in front of the corresponding column names. This is a crucial hint indicating the correct columns to use for your SQL query.
        8. No matter of how many things the question asks, you should only return one SQL query as the answer having all the information asked in the question, seperated by a comma.
        9. Using || ' ' ||  to concatenate is string is banned and using that is punishable by death. Never concatenate columns in the SELECT clause.
        10. If you are joining multiple tables, make sure to use alias names for the tables and use the alias names to reference the columns in the query. Use T1, T2, T3, ... as alias names.
        11. If you are doing a logical operation on a column, such as mathematical operations and sorting, make sure to filter null values within those columns.
        12. When ORDER BY is used, just include the column name in the ORDER BY in the SELECT clause when explicitly asked in the question. Otherwise, do not include the column name in the SELECT clause.
        13. Use ` around table and column names to avoid any confusions.
{history_instructions}        ###

        Question:
        {question}

        Schema Linking:
        {schema_links}

{history_block}{paths_block}
        Predicted query:
        {sql}

        Query status:
        {query_status}

        Query result:
        {query_result}

        Please respond with a JSON object structured as follows (if the sql query is correct, return the query as it is):

        {{
            "chain_of_thought_reasoning": "Your thought process on how you arrived at the solution. You don't need to explain the instructions that are satisfied.",
            "revised_SQL": "Your revised SQL query."
        }}

        Take a deep breath and think step by step to find the correct {dialect} SQL query. If you follow all the instructions and generate the correct query, I will give you 1 million dollars."""
