"""Prompt templates used by the DIN-SQL pipeline.

Sixteen templates across the four stages (schema linking, classification,
SQL generation per-label, self-correction) plus the LangChain wrappers that
glue them together via the make_*_prompt builders.

All template literals are verbatim from the original run_spider_din.py;
only the surrounding scaffolding (imports, builders, comments) is new.
"""

from __future__ import annotations

from langchain.prompts import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    SystemMessagePromptTemplate,
)


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
"""

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

"""

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
{history_block}{paths_block}A: Let’s think step by step."""

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
"""

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
"""

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
"""

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
"""

HUMAN_NON_NESTED_CLASS_TEMPLATE = """
Use the the schema links and intermediate reasoning steps to generate the correct sqlite SQL query for the given question.
###
Schema of the database with sample rows and column descriptions:
#
{schema}

#
Q: {question}
Schema_links: {schema_links}
{history_block}{paths_block}A: Let’s think step by step. """

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
"""

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
"""

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
"""

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
"""

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
"""

HUMAN_SELF_CORRECTION_PROMPT = """
Evaluate the correctness of this query for the given question.
Correct it if there are any issues. If there are no issues, return the SQLite SQL QUERY as is.
Schema of the database with sample rows and column descriptions:
#
{schema}

#
Q: {question}
SQL: {sql_query}
{history_block}{paths_block}A: Let's think step by step to find the correct answer."""


# ---------------------------------------------------------------------------
# LangChain wrappers (HumanMessage shells)
# ---------------------------------------------------------------------------

human_schema_linking_prompt = HumanMessagePromptTemplate.from_template(
    HUMAN_SCHEMA_LINKING_TEMPLATE
)
human_classification_prompt = HumanMessagePromptTemplate.from_template(
    HUMAN_CLASSIFICATION_TEMPLATE
)
human_easy_prompt = HumanMessagePromptTemplate.from_template(
    HUMAN_EASY_CLASS_TEMPLATE
)
human_medium_prompt = HumanMessagePromptTemplate.from_template(
    HUMAN_NON_NESTED_CLASS_TEMPLATE
)
human_hard_prompt = HumanMessagePromptTemplate.from_template(
    HUMAN_NESTED_CLASS_TEMPLATE
)
human_correction_prompt = HumanMessagePromptTemplate.from_template(
    HUMAN_SELF_CORRECTION_PROMPT
)


def _system(prompt: str) -> SystemMessagePromptTemplate:
    return SystemMessagePromptTemplate.from_template(prompt)


def make_schema_linking_prompt(use_view: bool = False) -> ChatPromptTemplate:
    """Stage 1 prompt; the basesql variant has no view fork, but DIN-SQL keeps
    the same template for both branches (kept here for symmetry with the
    classification / generation builders)."""
    return ChatPromptTemplate.from_messages([
        _system(SYSTEM_SCHEMA_LINKING_TEMPLATE),
        human_schema_linking_prompt,
    ])


def make_classification_prompt() -> ChatPromptTemplate:
    """Stage 2: classification + decomposition."""
    return ChatPromptTemplate.from_messages([
        _system(SYSTEM_CLASSIFICATION_TEMPLATE),
        human_classification_prompt,
    ])


def make_easy_prompt() -> ChatPromptTemplate:
    """Stage 3 (EASY label): direct SQL generation."""
    return ChatPromptTemplate.from_messages([
        _system(SYSTEM_EASY_CLASS_TEMPLATE),
        human_easy_prompt,
    ])


def make_non_nested_prompt(use_view: bool = False) -> ChatPromptTemplate:
    """Stage 3 (NON-NESTED label): SQL generation. use_view=True selects
    the _JOIN_VIEW variant containing extra view examples."""
    system = (
        SYSTEM_NON_NESTED_CLASS_TEMPLATE_JOIN_VIEW if use_view
        else SYSTEM_NON_NESTED_CLASS_TEMPLATE
    )
    return ChatPromptTemplate.from_messages([
        _system(system),
        human_medium_prompt,
    ])


def make_nested_prompt(use_view: bool = False) -> ChatPromptTemplate:
    """Stage 3 (NESTED label): SQL generation. use_view=True selects the
    _JOIN_VIEW variant containing extra view examples."""
    system = (
        SYSTEM_NESTED_CLASS_TEMPLATE_JOIN_VIEW if use_view
        else SYSTEM_NESTED_CLASS_TEMPLATE
    )
    return ChatPromptTemplate.from_messages([
        _system(system),
        human_hard_prompt,
    ])


def make_self_correction_prompt() -> ChatPromptTemplate:
    """Stage 4: self-correction."""
    return ChatPromptTemplate.from_messages([
        _system(SYSTEM_SELF_CORRECTION_PROMPT),
        human_correction_prompt,
    ])
