"""
Preprocessing for single-database mode.

Takes a CSV (question, db_id, SQL) and a single SQLite database path,
builds BM25 index, constructs prompts with schema + BM25 example values
(no evidence, no column descriptions).
"""
import json
import os
import re
import sqlite3
import argparse
import random
from collections import OrderedDict
from typing import List, Dict

from tqdm import tqdm
from nltk.tokenize import word_tokenize
from nltk import ngrams

from cscsql.service.process.process_dataset import (
    build_content_index,
    remove_contents_of_a_folder,
    sample_table_values,
    retrieve_relevant_hits,
    retrieve_question_related_db_values,
    obtain_n_grams,
    format_identifier,
    needs_backticks,
    input_prompt_template,
    deduplicate_dicts,
)

try:
    from pyserini.search.lucene import LuceneSearcher
except ImportError:
    LuceneSearcher = None


# Hardcoded subset of tables to use from the single database
ORIGINAL_TABLES = [
    'Country', 'Examination', 'Laboratory', 'League', 'Match', 'Patient',
    'Player', 'Player_Attributes', 'Team', 'Team_Attributes', 'account',
    'alignment', 'atom', 'attendance', 'attribute', 'badges', 'bond',
    'budget', 'card', 'cards', 'circuits', 'client', 'colour', 'comments',
    'connected', 'constructorResults', 'constructorStandings', 'constructors',
    'customers', 'disp', 'district', 'driverStandings', 'drivers', 'event',
    'expense', 'foreign_data', 'frpm', 'gasstations', 'gender',
    'hero_attribute', 'hero_power', 'income', 'lapTimes', 'legalities',
    'loan', 'major', 'member', 'molecule', 'order', 'pitStops',
    'postHistory', 'postLinks', 'posts', 'products', 'publisher',
    'qualifying', 'race', 'races', 'results', 'rulings', 'satscores',
    'schools', 'seasons', 'set_translations', 'sets', 'status', 'superhero',
    'superpower', 'tags', 'trans', 'transactions_1k', 'users', 'votes',
    'yearmonth', 'zip_code',
]

ORIGINAL_TABLES_VIEWS = ['cluster10_atom_join_bond_join_molecule',
 'cluster11_cards_join_legalities',
 'cluster12_cards_join_rulings',
 'cluster13_cards_join_set_translations',
 'cluster14_cards_join_foreign_data',
 'cluster15_set_translations_join_sets',
 'cluster16_cards_join_sets',
 'cluster17_posts_join_users',
 'cluster18_badges_join_users',
 'cluster19_comments_join_posts',
 'cluster1_frpm_join_schools',
 'cluster20_posthistory_join_posts_join_users',
 'cluster21_hero_power_join_superhero_join_superpower',
 'cluster22_publisher_join_superhero',
 'cluster23_colour_join_superhero',
 'cluster24_race_join_superhero',
 'cluster25_circuits_join_races',
 'cluster26_drivers_join_qualifying',
 'cluster27_races_join_results',
 'cluster28_drivers_join_results',
 'cluster29_driverstandings_join_drivers_join_races',
 'cluster2_satscores_join_schools',
 'cluster30_drivers_join_races_join_results',
 'cluster31_league_join_match',
 'cluster32_player_join_player_attributes',
 'cluster33_team_join_team_attributes',
 'cluster34_laboratory_join_patient',
 'cluster35_examination_join_patient',
 'cluster36_examination_join_laboratory_join_patient',
 'cluster37_examination_join_laboratory',
 'cluster38_major_join_member',
 'cluster39_budget_join_event',
 'cluster3_account_join_district',
 'cluster40_member_join_zip_code',
 'cluster41_expense_join_member',
 'cluster42_customers_join_yearmonth',
 'cluster43_gasstations_join_transactions_1k',
 'cluster44_account_join_district_join_loan',
 'cluster45_account_join_trans',
 'cluster46_card_join_client_join_disp',
 'cluster47_account_join_client_join_order',
 'cluster48_posts_join_tags',
 'cluster49_votes',
 'cluster4_client_join_district',
 'cluster50_postlinks_join_posts',
 'cluster51_attribute_join_hero_attribute_join_publisher_join_superhero',
 'cluster52_attribute_join_gender_join_hero_attribute_join_superhero',
 'cluster53_alignment_join_superhero',
 'cluster54_constructorstandings_join_constructors',
 'cluster55_races_join_seasons',
 'cluster56_drivers_join_laptimes',
 'cluster57_races_join_results_join_status',
 'cluster58_drivers_join_pitstops_join_races',
 'cluster59_circuits_join_races_join_pitstops_join_results',
 'cluster5_atom_join_bond',
 'cluster60_country_join_league',
 'cluster61_country_join_match_join_player',
 'cluster62_attendance_join_event_join_member',
 'cluster63_income_join_member',
 'cluster64_customers_join_transactions_1k_join_products',
 'cluster6_bond_join_molecule',
 'cluster7_atom_join_connected',
 'cluster8_atom_join_molecule',
 'cluster9_bond_join_connected']

RENAMED_TABLES = [
    'Bank_Accounts', 'Bank_Cards', 'Bank_Clients', 'Bank_Dispositions',
    'Bank_Districts', 'Bank_Loans', 'Bank_Orders', 'Bank_Transactions',
    'Chem_Atoms', 'Chem_Bonds', 'Chem_Links', 'Chem_Molecules',
    'Club_Attendance', 'Club_Budgets', 'Club_Events', 'Club_Expenses',
    'Club_Income', 'Club_Majors', 'Club_Members', 'Club_Zips',
    'Education_Lunch_Aid', 'Education_SAT_Stats', 'Education_Schools',
    'Energy_Customers', 'Energy_Products', 'Energy_Sales',
    'Energy_Stations', 'Energy_Usage', 'F1_Constructor_Results',
    'F1_Constructor_Standings', 'F1_Constructors', 'F1_Driver_Standings',
    'F1_Drivers', 'F1_Lap_Times', 'F1_Pit_Stops', 'F1_Qualifying',
    'F1_Races', 'F1_Results', 'F1_Seasons', 'F1_Status_Codes',
    'F1_Tracks', 'Forum_Badges', 'Forum_Comments', 'Forum_History',
    'Forum_Links', 'Forum_Posts', 'Forum_Tags', 'Forum_Users',
    'Forum_Votes', 'Hero_Alignments', 'Hero_Attribute_Types',
    'Hero_Attributes', 'Hero_Colors', 'Hero_Genders', 'Hero_Power_Map',
    'Hero_Profiles', 'Hero_Publishers', 'Hero_Races', 'Hero_Superpowers',
    'MTG_Card_Foreign_Data', 'MTG_Cards', 'MTG_Legality', 'MTG_Rulings',
    'MTG_Set_Translations', 'MTG_Sets', 'Medical_Exams',
    'Medical_Lab_Results', 'Medical_Patients', 'Soccer_Countries',
    'Soccer_Leagues', 'Soccer_Matches', 'Soccer_Player_Stats',
    'Soccer_Players', 'Soccer_Team_Stats', 'Soccer_Teams',
]

RENAMED_TABLES_VIEWS = ['workload_updated_cluster10_Chem_Atoms_join_Chem_Bonds_join_Chem_Molecules',
 'workload_updated_cluster11_MTG_Cards_join_MTG_Legality',
 'workload_updated_cluster12_MTG_Cards_join_MTG_Rulings',
 'workload_updated_cluster13_MTG_Cards_join_MTG_Set_Translations',
 'workload_updated_cluster14_MTG_Card_Foreign_Data_join_MTG_Cards',
 'workload_updated_cluster15_MTG_Set_Translations_join_MTG_Sets',
 'workload_updated_cluster16_MTG_Cards_join_MTG_Sets',
 'workload_updated_cluster17_Forum_Posts_join_Forum_Users',
 'workload_updated_cluster18_Forum_Badges_join_Forum_Users',
 'workload_updated_cluster19_Forum_Comments_join_Forum_Posts',
 'workload_updated_cluster1_Education_Lunch_Aid_join_Education_Schools',
 'workload_updated_cluster20_Forum_History_join_Forum_Posts_join_Forum_Users',
 'workload_updated_cluster21_Hero_Power_Map_join_Hero_Profiles_join_Hero_Superpowers',
 'workload_updated_cluster22_Hero_Profiles_join_Hero_Publishers',
 'workload_updated_cluster23_Hero_Colors_join_Hero_Profiles',
 'workload_updated_cluster24_Hero_Profiles_join_Hero_Races',
 'workload_updated_cluster25_F1_Races_join_F1_Tracks',
 'workload_updated_cluster26_F1_Drivers_join_F1_Qualifying',
 'workload_updated_cluster27_F1_Races_join_F1_Results',
 'workload_updated_cluster28_F1_Drivers_join_F1_Results',
 'workload_updated_cluster29_F1_Driver_Standings_join_F1_Drivers_join_F1_Races',
 'workload_updated_cluster2_Education_SAT_Stats_join_Education_Schools',
 'workload_updated_cluster30_F1_Drivers_join_F1_Races_join_F1_Results',
 'workload_updated_cluster31_Soccer_Leagues_join_Soccer_Matches',
 'workload_updated_cluster32_Soccer_Player_Stats_join_Soccer_Players',
 'workload_updated_cluster33_Soccer_Team_Stats_join_Soccer_Teams',
 'workload_updated_cluster34_Medical_Lab_Results_join_Medical_Patients',
 'workload_updated_cluster35_Medical_Exams_join_Medical_Patients',
 'workload_updated_cluster36_Medical_Exams_join_Medical_Lab_Results_join_Medical_Patients',
 'workload_updated_cluster37_Medical_Exams_join_Medical_Lab_Results',
 'workload_updated_cluster38_Club_Majors_join_Club_Members',
 'workload_updated_cluster39_Club_Budgets_join_Club_Events',
 'workload_updated_cluster3_Bank_Accounts_join_Bank_Districts',
 'workload_updated_cluster40_Club_Members_join_Club_Zips',
 'workload_updated_cluster41_Club_Expenses_join_Club_Members',
 'workload_updated_cluster42_Energy_Customers_join_Energy_Usage',
 'workload_updated_cluster43_Energy_Sales_join_Energy_Stations',
 'workload_updated_cluster44_Bank_Accounts_join_Bank_Districts_join_Bank_Loans',
 'workload_updated_cluster45_Bank_Accounts_join_Bank_Transactions',
 'workload_updated_cluster46_Bank_Cards_join_Bank_Clients_join_Bank_Dispositions',
 'workload_updated_cluster47_Bank_Accounts_join_Bank_Clients_join_Bank_Orders',
 'workload_updated_cluster48_Forum_Posts_join_Forum_Tags',
 'workload_updated_cluster49_Forum_Votes',
 'workload_updated_cluster4_Bank_Clients_join_Bank_Districts',
 'workload_updated_cluster50_Forum_Links_join_Forum_Posts',
 'workload_updated_cluster51_Hero_Attribute_Types_join_Hero_Attributes_join_Hero_Profiles_join_Hero_Publishers',
 'workload_updated_cluster52_Hero_Attribute_Types_join_Hero_Attributes_join_Hero_Genders_join_Hero_Profiles',
 'workload_updated_cluster53_Hero_Alignments_join_Hero_Profiles',
 'workload_updated_cluster54_F1_Constructor_Standings_join_F1_Constructors',
 'workload_updated_cluster55_F1_Races_join_F1_Seasons',
 'workload_updated_cluster56_F1_Drivers_join_F1_Lap_Times',
 'workload_updated_cluster57_F1_Races_join_F1_Results_join_F1_Status_Codes',
 'workload_updated_cluster58_F1_Drivers_join_F1_Pit_Stops_join_F1_Races',
 'workload_updated_cluster59_F1_Pit_Stops_join_F1_Races_join_F1_Results_join_F1_Tracks',
 'workload_updated_cluster5_Chem_Atoms_join_Chem_Bonds',
 'workload_updated_cluster60_Soccer_Countries_join_Soccer_Leagues',
 'workload_updated_cluster61_Soccer_Countries_join_Soccer_Matches_join_Soccer_Players',
 'workload_updated_cluster62_Club_Attendance_join_Club_Events_join_Club_Members',
 'workload_updated_cluster63_Club_Income_join_Club_Members',
 'workload_updated_cluster64_Energy_Customers_join_Energy_Products_join_Energy_Sales',
 'workload_updated_cluster6_Chem_Bonds_join_Chem_Molecules',
 'workload_updated_cluster7_Chem_Atoms_join_Chem_Links',
 'workload_updated_cluster8_Chem_Atoms_join_Chem_Molecules',
 'workload_updated_cluster9_Chem_Bonds_join_Chem_Links']

org_tables = ['conductor', 'orchestra', 'performance', 'show', 'airlines', 'airports', 'flights', 'Highschooler', 'Friend', 'Likes', 'players', 'matches', 'rankings', 'battle', 'ship', 'death', 'TV_Channel', 'TV_series', 'Cartoon', 'city', 'country', 'countrylanguage', 'course', 'teacher', 'course_arrange', 'Ref_Feature_Types', 'Ref_Property_Types', 'Other_Available_Features', 'Properties', 'Other_Property_Features', 'Ref_Template_Types', 'Templates', 'Documents', 'Paragraphs', 'continents', 'countries', 'car_makers', 'model_list', 'car_names', 'cars_data', 'poker_player', 'people', 'Addresses', 'Courses', 'Departments', 'Degree_Programs', 'Sections', 'Semesters', 'Students', 'Student_Enrolment', 'Student_Enrolment_Courses', 'Transcripts', 'Transcript_Contents', 'Breeds', 'Charges', 'Sizes', 'Treatment_Types', 'Owners', 'Dogs', 'Professionals', 'Treatments', 'Student', 'Has_Pet', 'Pets', 'employee', 'shop', 'hiring', 'evaluation', 'AREA_CODE_STATE', 'CONTESTANTS', 'stadium', 'singer', 'concert', 'singer_in_concert', 'museum', 'visitor', 'visit', 'VOTES']
renamed_tables = ['conductors', 'orchestras', 'performances', 'shows', 'airline_companies', 'airport_locations', 'flight_schedules', 'highschoolers', 'friends', 'student_likes', 'tennis_players', 'tennis_matches', 'tennis_rankings', 'battles', 'ships', 'deaths', 'tv_channels', 'tv_series_episodes', 'cartoons', 'cities', 'countries_info', 'country_languages', 'courses_info', 'teachers', 'course_arrangements', 'feature_types', 'property_types', 'available_features', 'property_listings', 'property_features', 'template_types', 'document_templates', 'managed_documents', 'document_paragraphs', 'continent_info', 'car_countries', 'car_manufacturers', 'car_models', 'car_make_names', 'car_data', 'poker_players', 'people_info', 'student_addresses', 'university_courses', 'university_departments', 'degree_programs_info', 'course_sections', 'academic_semesters', 'university_students', 'student_enrollments', 'student_enrolled_courses', 'student_transcripts', 'transcript_contents_info', 'dog_breeds', 'vet_charges', 'dog_sizes', 'vet_treatment_types', 'dog_owners', 'vet_dogs', 'vet_professionals', 'vet_treatments', 'pet_students', 'student_has_pet', 'student_pets', 'shop_employees', 'retail_shops', 'shop_hiring', 'employee_evaluations', 'state_area_codes', 'voting_contestants', 'contestant_votes', 'stadiums', 'singers', 'concerts', 'concert_singers', 'museums', 'museum_visitors', 'museum_visits']
org_views = ['cluster1_CARS_DATA_join_CAR_NAMES', 'cluster2_concert_join_stadium', 'cluster3_Documents_join_Templates', 'cluster4_Dogs_join_Treatments', 'cluster5_Professionals_join_Treatments', 'cluster6_Dogs_join_Owners', 'cluster7_AIRLINES_join_FLIGHTS', 'cluster8_AIRPORTS_join_FLIGHTS', 'cluster9_Friend_join_Highschooler', 'cluster10_Highschooler_join_Likes', 'cluster11_has_pet_join_student', 'cluster12_has_pet_join_pets_join_student', 'cluster13_people_join_poker_player', 'cluster14_TV_Channel_join_Cartoon', 'cluster15_country_join_countrylanguage', 'cluster16_death', 'cluster17_death_join_ship', 'cluster18_battle', 'cluster19_CAR_MAKERS_join_COUNTRIES', 'cluster20_continents', 'cluster21_CAR_MAKERS_join_MODEL_LIST', 'cluster22_singer', 'cluster23_concert_join_singer_in_concert', 'cluster24_teacher', 'cluster25_course_arrange_join_teacher', 'cluster26_course_join_course_arrange_join_teacher', 'cluster27_Documents_join_Paragraphs', 'cluster28_Ref_Template_Types', 'cluster29_Treatment_Types_join_Treatments_join_Professionals', 'cluster30_Breeds_join_Dogs', 'cluster31_Charges', 'cluster32_employee_join_evaluation', 'cluster33_hiring_join_shop', 'cluster34_visit_join_visitor', 'cluster35_museum', 'cluster36_orchestra', 'cluster37_show', 'cluster38_conductor_join_orchestra', 'cluster39_orchestra_join_performance', 'cluster40_Other_Available_Features_join_Ref_Feature_Types', 'cluster41_Properties_join_Ref_Property_Types', 'cluster42_Addresses', 'cluster43_Semesters_join_Student_Enrolment', 'cluster44_Courses_join_Sections', 'cluster45_Students', 'cluster46_Degree_Programs', 'cluster47_Transcript_Contents_join_Transcripts', 'cluster48_Courses_join_Student_Enrolment_Courses', 'cluster49_Degree_Programs_join_Departments', 'cluster50_Degree_Programs_join_Student_Enrolment_join_Students', 'cluster51_TV_series', 'cluster52_CONTESTANTS_join_VOTES', 'cluster53_AREA_CODE_STATE', 'cluster54_city_join_country_join_countrylanguage', 'cluster55_players', 'cluster56_matches', 'cluster57_rankings']
renamed_views = ['cluster1_car_data_join_car_make_names', 'cluster2_car_countries_join_car_manufacturers', 'cluster3_car_manufacturers_join_car_models', 'cluster4_concerts_join_stadiums', 'cluster5_document_templates_join_managed_documents', 'cluster6_vet_dogs_join_vet_treatments', 'cluster7_vet_professionals_join_vet_treatments', 'cluster8_dog_owners_join_vet_dogs', 'cluster9_airline_companies_join_flight_schedules', 'cluster10_airport_locations_join_flight_schedules', 'cluster11_friends_join_highschoolers', 'cluster12_highschoolers_join_student_likes', 'cluster13_pet_students_join_student_has_pet', 'cluster14_pet_students_join_student_has_pet_join_student_pets', 'cluster15_people_info_join_poker_players', 'cluster16_cartoons_join_tv_channels', 'cluster17_countries_info_join_country_languages', 'cluster18_deaths', 'cluster19_deaths_join_ships', 'cluster20_battles', 'cluster21_continent_info', 'cluster22_singers', 'cluster23_concert_singers_join_concerts', 'cluster24_teachers', 'cluster25_course_arrangements_join_teachers', 'cluster26_course_arrangements_join_courses_info_join_teachers', 'cluster27_document_paragraphs_join_managed_documents', 'cluster28_template_types', 'cluster29_vet_professionals_join_vet_treatment_types_join_vet_treatments', 'cluster30_dog_breeds_join_vet_dogs', 'cluster31_vet_charges', 'cluster32_employee_evaluations_join_shop_employees', 'cluster33_retail_shops_join_shop_hiring', 'cluster34_museum_visitors_join_museum_visits', 'cluster35_museums', 'cluster36_orchestras', 'cluster37_shows', 'cluster38_conductors_join_orchestras', 'cluster39_orchestras_join_performances', 'cluster40_available_features_join_feature_types', 'cluster41_property_listings_join_property_types', 'cluster42_student_addresses', 'cluster43_academic_semesters_join_student_enrollments', 'cluster44_course_sections_join_university_courses', 'cluster45_university_students', 'cluster46_degree_programs_info', 'cluster47_student_transcripts_join_transcript_contents_info', 'cluster48_student_enrolled_courses_join_university_courses', 'cluster49_degree_programs_info_join_university_departments', 'cluster50_degree_programs_info_join_student_enrollments_join_university_students', 'cluster51_tv_series_episodes', 'cluster52_contestant_votes_join_voting_contestants', 'cluster53_state_area_codes', 'cluster54_cities_join_countries_info_join_country_languages', 'cluster55_tennis_players', 'cluster56_tennis_matches', 'cluster57_tennis_rankings']


def get_allowed_tables(rename: bool = False, dataset: str = "bird"):
    """Return the appropriate table list based on rename flag and dataset."""
    if dataset == "spider":
        return renamed_tables if rename else org_tables
    return RENAMED_TABLES if rename else ORIGINAL_TABLES


def get_view_list(rename: bool = False, dataset: str = "bird"):
    """Return the appropriate view list based on rename flag and dataset."""
    if dataset == "spider":
        return renamed_views if rename else org_views
    return RENAMED_TABLES_VIEWS if rename else ORIGINAL_TABLES_VIEWS


def parse_view_tables(view_name: str) -> List[str]:
    """
    Extract constituent table names from a view name.
    E.g. 'cluster10_atom_join_bond_join_molecule' -> ['atom', 'bond', 'molecule']
    E.g. 'workload_updated_cluster3_Bank_Accounts_join_Bank_Districts' -> ['Bank_Accounts', 'Bank_Districts']
    """
    # Strip prefix: "workload_updated_cluster<N>_" or "cluster<N>_"
    match = re.match(r'^(?:workload_updated_)?cluster\d+_(.*)', view_name)
    if not match:
        return []
    tables_part = match.group(1)
    # Split on "_join_"
    return [t for t in tables_part.split("_join_") if t]


def find_matching_views(selected_tables: List[str], view_list: List[str]) -> List[str]:
    """
    Return views that contain at least 1 table from selected_tables.
    Matching is case-insensitive.
    """
    selected_lower = {t.lower() for t in selected_tables}
    matching = []
    for view_name in view_list:
        constituent_tables = parse_view_tables(view_name)
        for table in constituent_tables:
            if table.lower() in selected_lower:
                matching.append(view_name)
                break
    return matching


# Name-mapping files (produced alongside MAC-SQL). Used to reconstruct FKs for renamed tables
# since the merged sqlite stores renamed tables without FK constraints (PRAGMA returns empty).
# Bird direction:   column_mapping[renamed_table] = {original_col: renamed_col}
# Spider direction: column_mapping[renamed_table] = {renamed_col: original_col}
# Path resolution tries multiple candidates so the code works from both Windows and WSL.
def _find_first_existing(candidates):
    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]  # return first as fallback (will fail os.path.exists later — logged as warning)

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))  # .../benchmarks/csc_sql/src/cscsql/service/process/
# Mapping files live two directories above csc_sql/ (i.e., in the LDD root's mapping_files folder).
# Walking up: process -> service -> cscsql -> src -> csc_sql -> benchmarks -> LDD root.
_LDD_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", "..", "..", "..", ".."))
_MAPPING_DIR = os.path.join(_LDD_ROOT, "mapping_files")
_BIRD_MAPPING_PATH   = os.path.join(_MAPPING_DIR, "name_mapping_bird.json")
_SPIDER_MAPPING_PATH = os.path.join(_MAPPING_DIR, "name_mapping_spider.json")


def _lookup_renamed_col(inner_map: dict, orig_col: str, direction: str) -> str:
    """Translate an original (base-table) column name to its renamed form via the mapping."""
    if direction == "bird":
        # inner_map is {original_col: renamed_col}
        for k, v in inner_map.items():
            if str(k).lower() == orig_col.lower():
                return v
    else:  # spider: inner_map is {renamed_col: original_col}
        for k, v in inner_map.items():
            if str(v).lower() == orig_col.lower():
                return k
    return orig_col  # fallback: keep original (will likely fail the index lookup, but won't crash)


def supplement_renamed_fks(db_path: str, renamed_tables_in_list: list,
                           column_names_original: list, table_names_original: list,
                           dataset: str = "bird") -> list:
    """Reconstruct FK index pairs for renamed tables by walking base-table PRAGMA FKs
    and translating via the name mapping. Returns list of [from_idx, to_idx] pairs
    suitable for db_info['foreign_keys']."""
    import json
    mapping_path = _SPIDER_MAPPING_PATH if dataset == "spider" else _BIRD_MAPPING_PATH
    direction = "spider" if dataset == "spider" else "bird"
    if not os.path.exists(mapping_path):
        print(f"  [FK mapping] WARNING: {dataset} mapping file not found at {mapping_path} — renamed tables will have no FKs")
        return []

    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping = json.load(f)
    table_to_renamed = mapping.get("table_to_view", {})   # {orig_table: renamed_table}
    column_mapping   = mapping.get("column_mapping", {})  # {renamed_table: inner}

    # Reverse: renamed_table -> orig_table (case-insensitive)
    renamed_to_orig = {v.lower(): k for k, v in table_to_renamed.items()}
    renamed_set_lower = {t.lower() for t in renamed_tables_in_list}

    # Build a quick lookup: (table_name_lower, col_name_lower) -> global col index
    name_to_idx = {}
    for idx, (ti, cn) in enumerate(column_names_original):
        if ti >= 0:
            tname = table_names_original[ti]
            name_to_idx[(tname.lower(), cn.lower())] = idx

    conn = sqlite3.connect(db_path)
    conn.text_factory = lambda b: b.decode(errors="ignore")
    cursor = conn.cursor()

    out = []
    for renamed in renamed_tables_in_list:
        base_table = renamed_to_orig.get(renamed.lower())
        if not base_table:
            continue
        try:
            cursor.execute(f"PRAGMA foreign_key_list(`{base_table}`)")
        except sqlite3.OperationalError:
            continue
        fks = cursor.fetchall()
        for fk in fks:
            from_col_orig = fk[3]
            ref_table_orig = fk[2]
            to_col_orig = fk[4]
            if not (from_col_orig and ref_table_orig and to_col_orig):
                continue
            # Translate ref_table to renamed space
            ref_renamed = table_to_renamed.get(ref_table_orig)
            if not ref_renamed:
                for k, v in table_to_renamed.items():
                    if k.lower() == ref_table_orig.lower():
                        ref_renamed = v
                        break
            if not ref_renamed or ref_renamed.lower() not in renamed_set_lower:
                continue
            # Translate column names to renamed space
            from_col_renamed = _lookup_renamed_col(column_mapping.get(renamed, {}),      from_col_orig, direction)
            to_col_renamed   = _lookup_renamed_col(column_mapping.get(ref_renamed, {}),  to_col_orig,   direction)
            # Look up global indices
            from_idx = name_to_idx.get((renamed.lower(),     from_col_renamed.lower()))
            to_idx   = name_to_idx.get((ref_renamed.lower(), to_col_renamed.lower()))
            if from_idx is not None and to_idx is not None:
                pair = [from_idx, to_idx]
                if pair not in out:
                    out.append(pair)

    cursor.close()
    conn.close()
    return out


def get_db_info_from_sqlite(db_path: str, rename: bool = False, table_list: List[str] = None, quiet: bool = False, dataset: str = "bird") -> dict:
    """
    Build a tables.json-like db_info dict directly from a single SQLite file.
    No column descriptions — column_names mirrors column_names_original.
    If table_list is provided, use that instead of the allowed tables.
    """
    conn = sqlite3.connect(db_path)
    conn.text_factory = lambda b: b.decode(errors="ignore")
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE (type='table' OR type='view') AND name != 'sqlite_sequence' ORDER BY name;")
    all_table_names = [row[0] for row in cursor.fetchall()]
    # Filter to only allowed tables
    if table_list is not None:
        allowed_set = set(table_list)
    else:
        allowed_set = set(get_allowed_tables(rename, dataset=dataset))
    table_names = [t for t in all_table_names if t in allowed_set]
    if not quiet:
        print(f"Filtered tables: {len(table_names)}/{len(all_table_names)} (using {len(allowed_set)} allowed, rename={rename}, dataset={dataset})")

    column_names_original = [[-1, "*"]]  # placeholder for index 0
    column_names = [[-1, "*"]]
    column_types = ["text"]
    table_names_original = []
    primary_keys = []
    foreign_keys = []

    for table_idx, table_name in enumerate(table_names):
        table_names_original.append(table_name)

        cursor.execute(f"PRAGMA table_info(`{table_name}`);")
        columns = cursor.fetchall()
        pk_cols = []
        for col in columns:
            col_idx = len(column_names_original)
            col_name = col[1]
            col_type = col[2] if col[2] else "TEXT"
            is_pk = col[5]

            column_names_original.append([table_idx, col_name])
            column_names.append([table_idx, col_name])  # same as original — no descriptions
            column_types.append(col_type)

            if is_pk:
                pk_cols.append(col_idx)

        if pk_cols:
            if len(pk_cols) == 1:
                primary_keys.append(pk_cols[0])
            else:
                primary_keys.append(pk_cols)

        # Foreign keys
        cursor.execute(f"PRAGMA foreign_key_list(`{table_name}`);")
        fks = cursor.fetchall()
        for fk in fks:
            ref_table = fk[2]
            from_col = fk[3]
            to_col = fk[4]

            # Find column indices
            from_idx = None
            to_idx = None
            for idx, (ti, cn) in enumerate(column_names_original):
                if ti == table_idx and cn == from_col:
                    from_idx = idx
                if cn == to_col:
                    ref_ti = table_names.index(ref_table) if ref_table in table_names else -1
                    if ti == ref_ti:
                        to_idx = idx
            if from_idx is not None and to_idx is not None:
                foreign_keys.append([from_idx, to_idx])

    cursor.close()
    conn.close()

    # When rename=True, supplement foreign keys via name mapping (renamed tables have no
    # PRAGMA FKs in the merged sqlite; we reconstruct them from base-table FKs).
    if rename and table_names_original:
        extra_fks = supplement_renamed_fks(
            db_path=db_path,
            renamed_tables_in_list=table_names_original,
            column_names_original=column_names_original,
            table_names_original=table_names_original,
            dataset=dataset,
        )
        for pair in extra_fks:
            if pair not in foreign_keys:
                foreign_keys.append(pair)
        if not quiet and extra_fks:
            print(f"  Supplemented {len(extra_fks)} FK pairs from {dataset} name mapping")

    return {
        "db_id": "single_db",
        "table_names_original": table_names_original,
        "column_names_original": column_names_original,
        "column_names": column_names,  # same as original — no descriptions
        "column_types": column_types,
        "primary_keys": primary_keys,
        "foreign_keys": foreign_keys,
    }


def obtain_db_details_simple(db_info, sampled_db_values_dict, relavant_db_values_dict):
    """
    Build CREATE TABLE DDL strings with BM25 example values.
    No column descriptions, no random column dropping (dev mode — all columns included).
    """
    db_details = []

    for outer_table_idx, table_name in enumerate(db_info["table_names_original"]):
        column_info_list = []
        pk_columns = []
        fk_info = []

        for column_idx, ((inner_table_idx, column_name), column_type) in enumerate(zip(
                db_info["column_names_original"], db_info["column_types"]
        )):
            if inner_table_idx == outer_table_idx:
                column_values = []
                key = f"{table_name}.{column_name}".lower()
                if key in relavant_db_values_dict:
                    column_values.extend(relavant_db_values_dict[key])
                if key in sampled_db_values_dict:
                    column_values.extend(sampled_db_values_dict[key])
                column_values = list(dict.fromkeys(column_values))[:6]

                column_info = f'    {format_identifier(column_name)} {column_type},'
                if len(column_values) > 0:
                    column_info += f" -- example: {column_values}"

                column_info_list.append(column_info)

                for primary_keys_idx in db_info["primary_keys"]:
                    if isinstance(primary_keys_idx, int):
                        if column_idx == primary_keys_idx:
                            pk_columns.append(column_name)
                    elif isinstance(primary_keys_idx, list):
                        if column_idx in primary_keys_idx:
                            pk_columns.append(column_name)

                for (source_column_idx, target_column_idx) in db_info["foreign_keys"]:
                    if column_idx == source_column_idx:
                        source_table_idx = db_info["column_names_original"][source_column_idx][0]
                        source_table_name = db_info["table_names_original"][source_table_idx]
                        source_column_name = db_info["column_names_original"][source_column_idx][1]
                        target_table_idx_val = db_info["column_names_original"][target_column_idx][0]
                        target_table_name = db_info["table_names_original"][target_table_idx_val]
                        target_column_name = db_info["column_names_original"][target_column_idx][1]
                        fk_info.append(
                            f'    CONSTRAINT fk_{source_table_name.lower().replace(" ", "_")}_{source_column_name.lower().replace(" ", "_")} '
                            f'FOREIGN KEY ({format_identifier(source_column_name)}) '
                            f'REFERENCES {format_identifier(target_table_name)} ({format_identifier(target_column_name)}),')

        if len(column_info_list) > 0:
            pk_columns = list(OrderedDict.fromkeys(pk_columns))
            if len(pk_columns) > 0:
                pk_info = ['    PRIMARY KEY (' + ', '.join(
                    [f'{format_identifier(column_name)}' for column_name in pk_columns]) + '),']
            else:
                pk_info = []
            fk_info = list(OrderedDict.fromkeys(fk_info))

            table_ddl = f'CREATE TABLE {format_identifier(table_name)} (\n'
            table_ddl += "\n".join(column_info_list + pk_info + fk_info)
            if table_ddl.endswith(","):
                table_ddl = table_ddl[:-1]
            table_ddl += "\n);"
            db_details.append(table_ddl)

    return "\n\n".join(db_details)


def get_history_sql_cols(rename: bool = False, view: bool = False, dataset: str = "bird") -> List[str]:
    """
    Determine the SQL column name(s) in the history CSV based on flags.
    Returns a list of columns to retrieve top-k from each.

    bird:
    - No flags: ['SQL']
    - --rename: ['workload_updated_SQL']
    - --view: ['SQL', 'view_SQL']
    - --rename --view: ['workload_updated_SQL', 'workload_updated_view_SQL']

    spider:
    - No flags: ['SQL']
    - --rename: ['renamed_SQL']
    - --view: ['SQL', 'view_SQL']
    - --rename --view: ['renamed_SQL', 'renamed_view_SQL']
    """
    if dataset == "spider":
        base_col = 'renamed_SQL' if rename else 'SQL'
        cols = [base_col]
        if view:
            view_col = 'renamed_view_SQL' if rename else 'view_SQL'
            cols.append(view_col)
        return cols
    base_col = 'workload_updated_SQL' if rename else 'SQL'
    cols = [base_col]
    if view:
        view_col = 'workload_updated_view_SQL' if rename else 'view_SQL'
        cols.append(view_col)
    return cols


def get_gt_tables_col(rename: bool = False, dataset: str = "bird") -> str:
    """Determine the ground-truth tables column for cluster building."""
    if dataset == "spider":
        return 'gt_renamed_tables' if rename else 'gt_tables'
    return 'gt_workload_updated_tables' if rename else 'gt_tables'


def simplify_sql(query: str) -> str:
    """Simplify SQL to just the FROM/JOIN structure (for cluster path building)."""
    q = " ".join(str(query).strip().split())
    match = re.search(r"\bFROM\b", q, re.IGNORECASE)
    if not match:
        return q
    q_from = q[match.start():]
    stop_match = re.search(r"\b(WHERE|GROUP BY|ORDER BY|HAVING|LIMIT)\b", q_from, re.IGNORECASE)
    if stop_match:
        q_from = q_from[:stop_match.start()]
    return q_from.strip()


def normalize_table_name(name: str) -> str:
    """Normalize table name for comparison."""
    if name is None:
        return ""
    s = str(name).strip().strip('"').strip("'").strip('`').strip()
    s = re.sub(r'^[A-Za-z0-9_]+\.', '', s)
    s = re.sub(r'^\[[^\]]+\]\.', '', s)
    return s.upper()


def _cluster_norm_cache(clusters) -> Dict:
    return {
        c["cluster_id"]: {normalize_table_name(t) for t in c["tables"]}
        for c in clusters
    }


def find_best_cluster_combo_strict(query_tables, clusters):
    """Find best cluster match: exact > subset > combo of 2 > new."""
    from collections import Counter
    qset = {normalize_table_name(t) for t in query_tables}
    if not qset:
        return [], "new"

    clusters_sorted = sorted(clusters, key=lambda c: c["cluster_id"])
    norm_by_id = _cluster_norm_cache(clusters_sorted)

    # exact
    for c in clusters_sorted:
        if qset == norm_by_id[c["cluster_id"]]:
            return [c], "exact"

    # single superset
    supersets = [c for c in clusters_sorted if qset.issubset(norm_by_id[c["cluster_id"]])]
    if supersets:
        supersets.sort(key=lambda c: (len(c["tables"]), c["cluster_id"]))
        return [supersets[0]], "subset"

    # combo of 2
    candidates = [c for c in clusters_sorted if qset & norm_by_id[c["cluster_id"]]]
    best_pair, best_key = None, None
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

    return [], "new"


def find_exact_query_patterns(list_of_table_lists, path_list, min_frequency=5, min_tables=2):
    """Build initial frequent table clusters."""
    from collections import Counter, defaultdict
    exact_patterns = Counter()
    pattern_paths = defaultdict(set)

    for tables, path in zip(list_of_table_lists, path_list):
        key = frozenset(tables)
        exact_patterns[key] += 1
        pattern_paths[key].add(path)

    clusters = []
    cluster_id = 1
    for pattern, count in exact_patterns.items():
        if count >= min_frequency and len(pattern) >= min_tables:
            clusters.append({
                "cluster_id": cluster_id,
                "tables": sorted(pattern),
                "num_tables": len(pattern),
                "count": count,
                "paths": sorted(list(pattern_paths[pattern])),
                "questions": [],
                "indices": [],
                "match_types": [],
                "subsets": {},
                "combo_pairs": {}
            })
            cluster_id += 1

    clusters.sort(key=lambda x: (x["count"], x["num_tables"]), reverse=True)
    return clusters


def assign_queries_to_clusters(list_of_table_lists, clusters, question_list, path_list, min_tables=2):
    """Assign each question to exactly one cluster."""
    from collections import defaultdict
    question_cluster_map = []
    question_combo_map = {}
    assigned_questions = set()
    next_cluster_id = max([c["cluster_id"] for c in clusters], default=0) + 1

    for idx, tables in enumerate(list_of_table_lists):
        if not tables or idx in assigned_questions:
            question_cluster_map.append(-1)
            continue

        matched, match_type = find_best_cluster_combo_strict(tables, clusters)
        qtext, qpath = question_list[idx], path_list[idx]

        if len(matched) == 1:
            c = matched[0]
            c["indices"].append(idx)
            c["questions"].append(qtext)
            c["paths"].append(qpath)
            c["match_types"].append(match_type)
            question_cluster_map.append(c["cluster_id"])
            assigned_questions.add(idx)
        elif len(matched) == 2:
            c1, c2 = matched
            primary = c1 if c1["cluster_id"] < c2["cluster_id"] else c2
            partner = c2 if primary is c1 else c1
            primary["indices"].append(idx)
            primary["questions"].append(qtext)
            primary["paths"].append(qpath)
            primary["match_types"].append(match_type)
            primary["combo_pairs"][idx] = (primary["cluster_id"], partner["cluster_id"])
            question_combo_map[idx] = (primary["cluster_id"], partner["cluster_id"])
            question_cluster_map.append(primary["cluster_id"])
            assigned_questions.add(idx)
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
                "combo_pairs": {}
            }
            clusters.append(new_cluster)
            question_cluster_map.append(next_cluster_id)
            assigned_questions.add(idx)
            next_cluster_id += 1

    for c in clusters:
        c["count"] = len(c["indices"])

    question_cluster_map = [[n] for n in question_cluster_map]
    for k, v in question_combo_map.items():
        question_cluster_map[k] = list(v)

    return question_cluster_map


def find_all_clusters_for_tables(query_tables, clusters, sqlite_path=None):
    """Find ALL clusters that contain at least one of the query tables."""
    from itertools import chain
    qset = {normalize_table_name(t) for t in query_tables}
    if not qset:
        return {"match_type": "new", "cluster_ids": [], "tables": [], "paths": [],
                "questions": [], "indices": []}

    clusters_sorted = sorted(clusters, key=lambda c: c["cluster_id"])
    norm_by_id = {
        c["cluster_id"]: {normalize_table_name(t) for t in c["tables"]}
        for c in clusters_sorted
    }

    overlapping = [c for c in clusters_sorted if (qset & norm_by_id[c["cluster_id"]])]
    if not overlapping:
        return {"match_type": "new", "cluster_ids": [], "tables": [], "paths": [],
                "questions": [], "indices": []}

    any_exact = any(qset == norm_by_id[c["cluster_id"]] for c in overlapping)
    any_subset = any(qset < norm_by_id[c["cluster_id"]] for c in overlapping)
    match_type = "exact" if any_exact else ("subset" if any_subset else "partial")

    seen_indices = set()
    merged_questions, merged_indices = [], []
    for c in overlapping:
        for q, i in zip(c.get("questions", []), c.get("indices", [])):
            if i not in seen_indices:
                merged_questions.append(q)
                merged_indices.append(i)
                seen_indices.add(i)

    tables = sorted(set(chain.from_iterable(c["tables"] for c in overlapping)))
    paths = sorted(set(chain.from_iterable(c.get("paths", []) for c in overlapping)))

    return {
        "match_type": match_type,
        "cluster_ids": [c["cluster_id"] for c in overlapping],
        "tables": tables,
        "paths": paths,
        "questions": merged_questions,
        "indices": merged_indices,
    }


def precompute_history(history_path: str, output_dir: str, rename: bool = False,
                       view: bool = False, cluster: bool = False, db_path: str = None,
                       dataset: str = "bird"):
    """
    Precompute history embeddings and optionally build clusters.
    Saves everything needed for retrieval at inference time.
    """
    import pandas as pd
    import numpy as np
    from sentence_transformers import SentenceTransformer
    import ast

    history_df = pd.read_csv(history_path)
    sql_cols = get_history_sql_cols(rename, view, dataset=dataset)
    print(f"History: {len(history_df)} entries, SQL columns: {sql_cols}")

    # Validate columns
    for col in sql_cols:
        if col not in history_df.columns:
            print(f"WARNING: column '{col}' not found. Available: {list(history_df.columns)}")
            return

    # Compute embeddings
    model = SentenceTransformer('BAAI/bge-large-en-v1.5', device='cuda')
    #model = SentenceTransformer('BAAI/bge-large-en-v1.5', device='cpu')
    history_questions = history_df['question'].astype(str).tolist()
    history_texts = ["passage: " + q.strip() for q in history_questions]
    history_embs = model.encode(history_texts, normalize_embeddings=True, show_progress_bar=True)
    print(f"Encoded {len(history_embs)} history embeddings")

    # Save embeddingsw
    emb_path = os.path.join(output_dir, "history_embeddings.npy")
    np.save(emb_path, history_embs)
    print(f"Saved embeddings to {emb_path}")

    # Save history data needed for retrieval (questions + SQL columns)
    history_data = {
        "questions": history_questions,
    }
    for col in sql_cols:
        history_data[col] = history_df[col].astype(str).tolist()
    history_data_path = os.path.join(output_dir, "history_data.json")
    with open(history_data_path, "w", encoding="utf-8") as f:
        json.dump(history_data, f, ensure_ascii=False)
    print(f"Saved history data to {history_data_path}")

    # Build clusters if requested
    if cluster:
        gt_col = get_gt_tables_col(rename, dataset=dataset)
        base_sql_col = sql_cols[0]  # First entry is the base SQL column

        if gt_col not in history_df.columns:
            print(f"WARNING: cluster column '{gt_col}' not found. Skipping cluster building.")
            return
        if base_sql_col not in history_df.columns:
            print(f"WARNING: SQL column '{base_sql_col}' not found. Skipping cluster building.")
            return

        # Build path list
        path_list = []
        for _, row in history_df.iterrows():
            path_list.append(simplify_sql(str(row[base_sql_col])))

        question_list = history_questions
        t_list = [ast.literal_eval(str(x)) for x in history_df[gt_col].tolist()]

        exact_clusters = find_exact_query_patterns(t_list, path_list, min_frequency=5, min_tables=2)
        assign_queries_to_clusters(t_list, exact_clusters, question_list, path_list, min_tables=2)

        print(f"Built {len(exact_clusters)} clusters")

        # Save clusters (convert sets/non-serializable types)
        clusters_path = os.path.join(output_dir, "history_clusters.json")
        # Clean combo_pairs keys (int -> str for JSON)
        for c in exact_clusters:
            c["combo_pairs"] = {str(k): v for k, v in c["combo_pairs"].items()}
        with open(clusters_path, "w", encoding="utf-8") as f:
            json.dump(exact_clusters, f, indent=2, ensure_ascii=False)
        print(f"Saved clusters to {clusters_path}")


def process_csv_to_prompts(csv_path: str, db_path: str, output_path: str,
                           bm25_index_path: str = None, value_limit_num: int = 2,
                           rename: bool = False, view: bool = False,
                           test_rows: str = None, history_path: str = None,
                           history_k: int = 7, cluster: bool = False,
                           dataset_name: str = "bird",
                           stage0_from: str = None):
    """
    Main preprocessing function.

    Args:
        csv_path: Path to CSV with columns: question, db_id, SQL
        db_path: Path to the single SQLite database file
        output_path: Where to write the processed JSON
        bm25_index_path: Where to store/load BM25 index (if None, skip BM25)
        value_limit_num: Number of sampled values per column
        rename: Use renamed tables
        view: Pre-generate view DDLs for injection in Stage 2+3
    """
    import pandas as pd
    df = pd.read_csv(csv_path)
    if test_rows is not None:
        if ':' in str(test_rows):
            start, end = test_rows.split(':')
            start, end = int(start), int(end)
            df = df.iloc[start:end].reset_index(drop=True)
            print(f"TEST MODE: using rows {start}:{end} ({len(df)} rows)")
        else:
            n = int(test_rows)
            df = df.head(n)
            print(f"TEST MODE: using first {n} rows")

    # Precompute history embeddings + clusters (retrieval happens at inference time)
    if history_path:
        output_dir = os.path.dirname(output_path) or "."
        print(f"Precomputing history from {history_path}...")
        precompute_history(
            history_path=history_path, output_dir=output_dir,
            rename=rename, view=view, cluster=cluster, db_path=db_path,
            dataset=dataset_name,
        )

    # Build db_info from SQLite
    db_info = get_db_info_from_sqlite(db_path, rename=rename, dataset=dataset_name)
    print(f"Loaded schema: {len(db_info['table_names_original'])} tables")

    # --- STAGE 0 PRE-PRUNING ---
    # When stage0_from is set, load prior Stage 1 output + clusters, and for each question
    # compute the cluster-union table set. The schema DDL injected into Stage 1's prompt will
    # be pruned to only those tables (per-question), moving the cluster_filter expansion
    # from between-Stage1-and-Stage2 to before-Stage1.
    stage0_per_question_tables = None  # list[list[str]] parallel to df rows, or None
    if stage0_from:
        stage0_link_file = os.path.join(stage0_from, "sampling_think_table_link.json")
        print(f"[stage0] Loading prior Stage 1 from {stage0_link_file}")
        prior_stage1 = FileUtils.load_json(stage0_link_file) if 'FileUtils' in globals() else json.load(open(stage0_link_file, encoding='utf-8'))
        # Load clusters (precompute_history above wrote them to output_dir)
        output_dir = os.path.dirname(output_path) or "."
        clusters_path = os.path.join(output_dir, "history_clusters.json")
        if not os.path.exists(clusters_path):
            raise FileNotFoundError(f"[stage0] clusters missing at {clusters_path} (precompute_history must have been called with cluster=True)")
        with open(clusters_path, 'r', encoding='utf-8') as f:
            stage0_clusters = json.load(f)
        print(f"[stage0] Loaded {len(stage0_clusters)} clusters")

        # For each question: extract prior predicted tables, match clusters, get cluster-union
        allowed_set = set(get_allowed_tables(rename, dataset=dataset_name))
        stage0_per_question_tables = []
        for q_idx in range(len(df)):
            # Match by position — prior Stage 1 json is a list indexed by question order
            if q_idx >= len(prior_stage1):
                stage0_per_question_tables.append(None)  # fall back to full schema
                continue
            item = prior_stage1[q_idx]
            # Extract predicted_tables: union across pred_sqls samples, filtered to allowed tables
            raw = []
            for gen in item.get("pred_sqls", []):
                raw.extend(gen)
            predicted_tables = list(set(raw) & allowed_set)
            if not predicted_tables:
                stage0_per_question_tables.append(None)
                continue
            # Match against clusters → union of cluster tables
            res = find_all_clusters_for_tables(predicted_tables, stage0_clusters)
            cluster_union = sorted(set(res.get("tables", [])) & allowed_set) if res.get("tables") else []
            stage0_per_question_tables.append(cluster_union if cluster_union else None)
        n_pruned = sum(1 for t in stage0_per_question_tables if t)
        print(f"[stage0] pre-pruned schema for {n_pruned}/{len(df)} questions (rest fall back to full schema)")

    # Sample values from DB
    sampled_db_values_dict = sample_table_values(
        db_path, db_info["table_names_original"], value_limit_num
    )

    # Pre-generate view DDLs if --view is enabled
    view_ddls = {}
    if view:
        view_list = get_view_list(rename, dataset=dataset_name)
        print(f"Pre-generating DDLs for {len(view_list)} views...")
        view_db_info = get_db_info_from_sqlite(db_path, rename=rename, table_list=view_list, dataset=dataset_name)
        view_sampled_values = sample_table_values(
            db_path, view_db_info["table_names_original"], value_limit_num
        )
        # Generate DDL per view
        for view_name in view_db_info["table_names_original"]:
            single_view_info = get_db_info_from_sqlite(db_path, rename=rename, table_list=[view_name], quiet=True, dataset=dataset_name)
            ddl = obtain_db_details_simple(single_view_info, view_sampled_values, {})
            if ddl.strip():
                view_ddls[view_name] = ddl
        print(f"Generated DDLs for {len(view_ddls)} views")

    # Build BM25 index for the single database
    searcher = None
    if bm25_index_path:
        index_dir = os.path.join(bm25_index_path, "single_db")
        if not os.path.exists(os.path.join(index_dir, "segments_1")):
            print("Building BM25 index (all tables)...")
            remove_contents_of_a_folder(index_dir)
            build_content_index(db_path, index_dir)
        if LuceneSearcher is not None:
            searcher = LuceneSearcher(index_dir)
            print("BM25 searcher loaded")
        else:
            print("WARNING: pyserini not installed, skipping BM25")

    # Batch retrieve BM25 hits for all questions
    db_id2relevant_hits = None
    if searcher is not None:
        all_queries = []
        for _, row in df.iterrows():
            question = str(row["question"])
            queries = obtain_n_grams(question, 8) + [question]
            all_queries.extend(queries)
        all_queries = list(set(all_queries))
        print(f"Retrieving BM25 hits for {len(all_queries)} unique queries...")
        all_hits = retrieve_relevant_hits(searcher, all_queries)
        # Filter hits to only allowed tables
        allowed_set = set(get_allowed_tables(rename, dataset=dataset_name))
        filtered_hits = {}
        for query, hits in all_hits.items():
            filtered_hits[query] = [
                h for h in hits if h["id"].split("-**-")[0] in allowed_set
            ]
        # Wrap in a single-key dict to match original interface
        db_id2relevant_hits = {"single_db": filtered_hits}

    # Build prompts
    dataset = []
    for idx, row in tqdm(df.iterrows(), total=len(df), desc="Building prompts"):
        question = str(row["question"])

        # BM25 retrieval for this question
        relavant_db_values_dict = {}
        if db_id2relevant_hits is not None:
            queries = obtain_n_grams(question, 8) + [question]
            queries = list(dict.fromkeys(queries))
            hits = []
            for query in queries:
                if query in db_id2relevant_hits["single_db"]:
                    hits.extend(db_id2relevant_hits["single_db"][query])
            hits = deduplicate_dicts(hits)
            relavant_db_values_dict = retrieve_question_related_db_values(hits, question)

        # Stage 0 pre-pruning: rebuild db_info for just this question's cluster-union tables
        if stage0_per_question_tables is not None and stage0_per_question_tables[idx]:
            pruned_db_info = get_db_info_from_sqlite(
                db_path, rename=rename,
                table_list=stage0_per_question_tables[idx],
                quiet=True, dataset=dataset_name,
            )
            db_details = obtain_db_details_simple(
                pruned_db_info, sampled_db_values_dict, relavant_db_values_dict
            )
        else:
            db_details = obtain_db_details_simple(
                db_info, sampled_db_values_dict, relavant_db_values_dict
            )

        input_seq = input_prompt_template.format(
            db_engine="SQLite",
            db_details=db_details,
            question=question
        )

        gold_sql = str(row.get("SQL", row.get("sql", "")))

        item = {
            "id": idx,
            "db_id": "single_db",
            "input_seq": input_seq,
            "output_seq": gold_sql,
            "output": gold_sql,
        }
        dataset.append(item)

    # Write output
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(dataset)} prompts to {output_path}")

    # Also write a gold SQL file for evaluation
    gold_sql_path = output_path.replace(".json", "_gold.sql")
    gold_lines = []
    for item in dataset:
        gold_lines.append(f"{item['output_seq']}\t----- {dataset_name} -----\tsingle_db")
    with open(gold_sql_path, "w", encoding="utf-8") as f:
        f.write("\n".join(gold_lines))
    print(f"Wrote gold SQL to {gold_sql_path}")

    # Save view DDLs if generated
    if view_ddls:
        view_ddls_path = output_path.replace(".json", "_view_ddls.json")
        with open(view_ddls_path, "w", encoding="utf-8") as f:
            json.dump(view_ddls, f, indent=2, ensure_ascii=False)
        print(f"Wrote {len(view_ddls)} view DDLs to {view_ddls_path}")

    return dataset


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Preprocess CSV + single DB for CSC-SQL pipeline")
    parser.add_argument("--csv_path", type=str, required=True, help="Path to CSV (question, db_id, SQL)")
    parser.add_argument("--db_path", type=str, required=True, help="Path to single SQLite database")
    parser.add_argument("--output_path", type=str, required=True, help="Output JSON path")
    parser.add_argument("--bm25_index_path", type=str, default=None, help="Directory for BM25 index")
    parser.add_argument("--value_limit_num", type=int, default=2, help="Sample values per column")
    parser.add_argument("--rename", action="store_true", help="Use renamed tables instead of original")
    parser.add_argument("--view", action="store_true", help="Pre-generate view DDLs for Stage 2+3")
    parser.add_argument("--dataset", type=str, default="bird", choices=["bird", "spider"], help="Dataset: bird or spider")

    args = parser.parse_args()
    process_csv_to_prompts(
        csv_path=args.csv_path,
        db_path=args.db_path,
        output_path=args.output_path,
        bm25_index_path=args.bm25_index_path,
        value_limit_num=args.value_limit_num,
        rename=args.rename,
        view=args.view,
        dataset_name=args.dataset,
    )
