-- Benchmark view layer for spider-Union.
-- Extracted from merged_spider.sqlite by create_database.py --dump_benchmark.
-- Replay onto a merged base database with --recreate_benchmark.
-- Families are emitted in dependency order; the renamed cluster views read the
-- renamed table views, so they come last.


-- ==== renamed_tables (78) ======================================
DROP VIEW IF EXISTS "conductors";
CREATE VIEW conductors AS
SELECT
    "Conductor_ID" AS conductor_id,
    "Name" AS name,
    "Age" AS age,
    "Nationality" AS nationality,
    "Year_of_Work" AS years_of_work
FROM conductor;
DROP VIEW IF EXISTS "orchestras";
CREATE VIEW orchestras AS
SELECT
    "Orchestra_ID" AS orchestra_id,
    "Orchestra" AS orchestra_name,
    "Conductor_ID" AS conductor_id,
    "Record_Company" AS record_company,
    "Year_of_Founded" AS year_founded,
    "Major_Record_Format" AS major_record_format
FROM orchestra;
DROP VIEW IF EXISTS "performances";
CREATE VIEW performances AS
SELECT
    "Performance_ID" AS performance_id,
    "Orchestra_ID" AS orchestra_id,
    "Type" AS performance_type,
    "Date" AS performance_date,
    "Official_ratings_(millions)" AS official_ratings_millions,
    "Weekly_rank" AS weekly_rank,
    "Share" AS audience_share
FROM performance;
DROP VIEW IF EXISTS "shows";
CREATE VIEW shows AS
SELECT
    "Show_ID" AS show_id,
    "Performance_ID" AS performance_id,
    "If_first_show" AS is_first_show,
    "Result" AS result,
    "Attendance" AS attendance
FROM show;
DROP VIEW IF EXISTS "airline_companies";
CREATE VIEW airline_companies AS
SELECT
    uid AS airline_id,
    Airline AS airline_name,
    Abbreviation AS abbreviation,
    Country AS country
FROM airlines;
DROP VIEW IF EXISTS "airport_locations";
CREATE VIEW airport_locations AS
SELECT
    City AS city,
    AirportCode AS airport_code,
    AirportName AS airport_name,
    Country AS country,
    CountryAbbrev AS country_abbrev
FROM airports;
DROP VIEW IF EXISTS "flight_schedules";
CREATE VIEW flight_schedules AS
SELECT
    Airline AS airline_id,
    FlightNo AS flight_number,
    SourceAirport AS source_airport,
    DestAirport AS dest_airport
FROM flights;
DROP VIEW IF EXISTS "highschoolers";
CREATE VIEW highschoolers AS
SELECT
    ID AS student_id,
    name AS name,
    grade AS grade
FROM Highschooler;
DROP VIEW IF EXISTS "friends";
CREATE VIEW friends AS
SELECT
    student_id AS student_id,
    friend_id AS friend_id
FROM Friend;
DROP VIEW IF EXISTS "student_likes";
CREATE VIEW student_likes AS
SELECT
    student_id AS student_id,
    liked_id AS liked_id
FROM Likes;
DROP VIEW IF EXISTS "tennis_players";
CREATE VIEW tennis_players AS
SELECT
    "player_id" AS player_id,
    "first_name" AS first_name,
    "last_name" AS last_name,
    "hand" AS hand,
    "birth_date" AS birth_date,
    "country_code" AS country_code
FROM players;
DROP VIEW IF EXISTS "tennis_matches";
CREATE VIEW tennis_matches AS
SELECT
    "best_of" AS best_of,
    "draw_size" AS draw_size,
    "loser_age" AS loser_age,
    "loser_entry" AS loser_entry,
    "loser_hand" AS loser_hand,
    "loser_ht" AS loser_height,
    "loser_id" AS loser_id,
    "loser_ioc" AS loser_ioc,
    "loser_name" AS loser_name,
    "loser_rank" AS loser_rank,
    "loser_rank_points" AS loser_rank_points,
    "loser_seed" AS loser_seed,
    "match_num" AS match_num,
    "minutes" AS minutes,
    "round" AS round,
    "score" AS score,
    "surface" AS surface,
    "tourney_date" AS tourney_date,
    "tourney_id" AS tourney_id,
    "tourney_level" AS tourney_level,
    "tourney_name" AS tourney_name,
    "winner_age" AS winner_age,
    "winner_entry" AS winner_entry,
    "winner_hand" AS winner_hand,
    "winner_ht" AS winner_height,
    "winner_id" AS winner_id,
    "winner_ioc" AS winner_ioc,
    "winner_name" AS winner_name,
    "winner_rank" AS winner_rank,
    "winner_rank_points" AS winner_rank_points,
    "winner_seed" AS winner_seed,
    "year" AS year
FROM matches;
DROP VIEW IF EXISTS "tennis_rankings";
CREATE VIEW tennis_rankings AS
SELECT
    "ranking_date" AS ranking_date,
    "ranking" AS ranking,
    "player_id" AS player_id,
    "ranking_points" AS ranking_points,
    "tours" AS tours
FROM rankings;
DROP VIEW IF EXISTS "battles";
CREATE VIEW battles AS
SELECT
    "id" AS battle_id,
    "name" AS name,
    "date" AS date,
    "bulgarian_commander" AS bulgarian_commander,
    "latin_commander" AS latin_commander,
    "result" AS result
FROM battle;
DROP VIEW IF EXISTS "ships";
CREATE VIEW ships AS
SELECT
    "lost_in_battle" AS lost_in_battle_id,
    "id" AS ship_id,
    "name" AS name,
    "tonnage" AS tonnage,
    "ship_type" AS ship_type,
    "location" AS location,
    "disposition_of_ship" AS disposition_of_ship
FROM ship;
DROP VIEW IF EXISTS "deaths";
CREATE VIEW deaths AS
SELECT
    "caused_by_ship_id" AS caused_by_ship_id,
    "id" AS death_id,
    "note" AS note,
    "killed" AS killed,
    "injured" AS injured
FROM death;
DROP VIEW IF EXISTS "tv_channels";
CREATE VIEW tv_channels AS
SELECT
    "id" AS channel_id,
    "series_name" AS series_name,
    "Country" AS country,
    "Language" AS language,
    "Content" AS content,
    "Pixel_aspect_ratio_PAR" AS pixel_aspect_ratio,
    "Hight_definition_TV" AS high_definition_tv,
    "Pay_per_view_PPV" AS pay_per_view,
    "Package_Option" AS package_option
FROM TV_Channel;
DROP VIEW IF EXISTS "tv_series_episodes";
CREATE VIEW tv_series_episodes AS
SELECT
    "id" AS series_id,
    "Episode" AS episode,
    "Air_Date" AS air_date,
    "Rating" AS rating,
    "Share" AS share,
    "18_49_Rating_Share" AS rating_share_18_49,
    "Viewers_m" AS viewers_millions,
    "Weekly_Rank" AS weekly_rank,
    "Channel" AS channel_id
FROM TV_series;
DROP VIEW IF EXISTS "cartoons";
CREATE VIEW cartoons AS
SELECT
    "id" AS cartoon_id,
    "Title" AS title,
    "Directed_by" AS directed_by,
    "Written_by" AS written_by,
    "Original_air_date" AS original_air_date,
    "Production_code" AS production_code,
    "Channel" AS channel_id
FROM Cartoon;
DROP VIEW IF EXISTS "cities";
CREATE VIEW cities AS
SELECT
    "ID" AS city_id,
    "Name" AS name,
    "CountryCode" AS country_code,
    "District" AS district,
    "Population" AS population
FROM city;
DROP VIEW IF EXISTS "countries_info";
CREATE VIEW countries_info AS
SELECT
    "Code" AS country_code,
    "Name" AS name,
    "Continent" AS continent,
    "Region" AS region,
    "SurfaceArea" AS surface_area,
    "IndepYear" AS indep_year,
    "Population" AS population,
    "LifeExpectancy" AS life_expectancy,
    "GNP" AS gnp,
    "GNPOld" AS gnp_old,
    "LocalName" AS local_name,
    "GovernmentForm" AS government_form,
    "HeadOfState" AS head_of_state,
    "Capital" AS capital,
    "Code2" AS code2
FROM country;
DROP VIEW IF EXISTS "country_languages";
CREATE VIEW country_languages AS
SELECT
    "CountryCode" AS country_code,
    "Language" AS language,
    "IsOfficial" AS is_official,
    "Percentage" AS percentage
FROM countrylanguage;
DROP VIEW IF EXISTS "courses_info";
CREATE VIEW courses_info AS
SELECT
    "Course_ID" AS course_id,
    "Staring_Date" AS starting_date,
    "Course" AS course_name
FROM course;
DROP VIEW IF EXISTS "teachers";
CREATE VIEW teachers AS
SELECT
    "Teacher_ID" AS teacher_id,
    "Name" AS name,
    "Age" AS age,
    "Hometown" AS hometown
FROM teacher;
DROP VIEW IF EXISTS "course_arrangements";
CREATE VIEW course_arrangements AS
SELECT
    "Course_ID" AS course_id,
    "Teacher_ID" AS teacher_id,
    "Grade" AS grade
FROM course_arrange;
DROP VIEW IF EXISTS "feature_types";
CREATE VIEW feature_types AS
SELECT
    "feature_type_code" AS feature_type_code,
    "feature_type_name" AS feature_type_name
FROM Ref_Feature_Types;
DROP VIEW IF EXISTS "property_types";
CREATE VIEW property_types AS
SELECT
    "property_type_code" AS property_type_code,
    "property_type_description" AS property_type_description
FROM Ref_Property_Types;
DROP VIEW IF EXISTS "available_features";
CREATE VIEW available_features AS
SELECT
    "feature_id" AS feature_id,
    "feature_type_code" AS feature_type_code,
    "feature_name" AS feature_name,
    "feature_description" AS feature_description
FROM Other_Available_Features;
DROP VIEW IF EXISTS "property_listings";
CREATE VIEW property_listings AS
SELECT
    "property_id" AS property_id,
    "property_type_code" AS property_type_code,
    "date_on_market" AS date_on_market,
    "date_sold" AS date_sold,
    "property_name" AS property_name,
    "property_address" AS property_address,
    "room_count" AS room_count,
    "vendor_requested_price" AS vendor_requested_price,
    "buyer_offered_price" AS buyer_offered_price,
    "agreed_selling_price" AS agreed_selling_price,
    "apt_feature_1" AS apt_feature_1,
    "apt_feature_2" AS apt_feature_2,
    "apt_feature_3" AS apt_feature_3,
    "fld_feature_1" AS fld_feature_1,
    "fld_feature_2" AS fld_feature_2,
    "fld_feature_3" AS fld_feature_3,
    "hse_feature_1" AS hse_feature_1,
    "hse_feature_2" AS hse_feature_2,
    "hse_feature_3" AS hse_feature_3,
    "oth_feature_1" AS oth_feature_1,
    "oth_feature_2" AS oth_feature_2,
    "oth_feature_3" AS oth_feature_3,
    "shp_feature_1" AS shp_feature_1,
    "shp_feature_2" AS shp_feature_2,
    "shp_feature_3" AS shp_feature_3,
    "other_property_details" AS other_property_details
FROM Properties;
DROP VIEW IF EXISTS "property_features";
CREATE VIEW property_features AS
SELECT
    "property_id" AS property_id,
    "feature_id" AS feature_id,
    "property_feature_description" AS property_feature_description
FROM Other_Property_Features;
DROP VIEW IF EXISTS "template_types";
CREATE VIEW template_types AS
SELECT
    "Template_Type_Code" AS template_type_code,
    "Template_Type_Description" AS template_type_description
FROM Ref_Template_Types;
DROP VIEW IF EXISTS "document_templates";
CREATE VIEW document_templates AS
SELECT
    "Template_ID" AS template_id,
    "Version_Number" AS version_number,
    "Template_Type_Code" AS template_type_code,
    "Date_Effective_From" AS date_effective_from,
    "Date_Effective_To" AS date_effective_to,
    "Template_Details" AS template_details
FROM Templates;
DROP VIEW IF EXISTS "managed_documents";
CREATE VIEW managed_documents AS
SELECT
    "Document_ID" AS document_id,
    "Template_ID" AS template_id,
    "Document_Name" AS document_name,
    "Document_Description" AS document_description,
    "Other_Details" AS other_details
FROM Documents;
DROP VIEW IF EXISTS "document_paragraphs";
CREATE VIEW document_paragraphs AS
SELECT
    "Paragraph_ID" AS paragraph_id,
    "Document_ID" AS document_id,
    "Paragraph_Text" AS paragraph_text,
    "Other_Details" AS other_details
FROM Paragraphs;
DROP VIEW IF EXISTS "continent_info";
CREATE VIEW continent_info AS
SELECT
    "ContId" AS cont_id,
    "Continent" AS continent
FROM continents;
DROP VIEW IF EXISTS "car_countries";
CREATE VIEW car_countries AS
SELECT
    "CountryId" AS country_id,
    "CountryName" AS country_name,
    "Continent" AS continent
FROM countries;
DROP VIEW IF EXISTS "car_manufacturers";
CREATE VIEW car_manufacturers AS
SELECT
    "Id" AS maker_id,
    "Maker" AS maker,
    "FullName" AS full_name,
    "Country" AS country
FROM car_makers;
DROP VIEW IF EXISTS "car_models";
CREATE VIEW car_models AS
SELECT
    "ModelId" AS model_id,
    "Maker" AS maker_id,
    "Model" AS model
FROM model_list;
DROP VIEW IF EXISTS "car_make_names";
CREATE VIEW car_make_names AS
SELECT
    "MakeId" AS make_id,
    "Model" AS model,
    "Make" AS make
FROM car_names;
DROP VIEW IF EXISTS "car_data";
CREATE VIEW car_data AS
SELECT
    "Id" AS make_id,
    "MPG" AS mpg,
    "Cylinders" AS cylinders,
    "Edispl" AS edispl,
    "Horsepower" AS horsepower,
    "Weight" AS weight,
    "Accelerate" AS accelerate,
    "Year" AS year
FROM cars_data;
DROP VIEW IF EXISTS "poker_players";
CREATE VIEW poker_players AS
SELECT
    "Poker_Player_ID" AS poker_player_id,
    "People_ID" AS people_id,
    "Final_Table_Made" AS final_table_made,
    "Best_Finish" AS best_finish,
    "Money_Rank" AS money_rank,
    "Earnings" AS earnings
FROM poker_player;
DROP VIEW IF EXISTS "people_info";
CREATE VIEW people_info AS
SELECT
    "People_ID" AS people_id,
    "Nationality" AS nationality,
    "Name" AS name,
    "Birth_Date" AS birth_date,
    "Height" AS height
FROM people;
DROP VIEW IF EXISTS "student_addresses";
CREATE VIEW student_addresses AS
SELECT
    "address_id" AS address_id,
    "line_1" AS line_1,
    "line_2" AS line_2,
    "line_3" AS line_3,
    "city" AS city,
    "zip_postcode" AS zip_postcode,
    "state_province_county" AS state_province_county,
    "country" AS country,
    "other_address_details" AS other_address_details
FROM Addresses;
DROP VIEW IF EXISTS "university_courses";
CREATE VIEW university_courses AS
SELECT
    "course_id" AS course_id,
    "course_name" AS course_name,
    "course_description" AS course_description,
    "other_details" AS other_details
FROM Courses;
DROP VIEW IF EXISTS "university_departments";
CREATE VIEW university_departments AS
SELECT
    "department_id" AS department_id,
    "department_name" AS department_name,
    "department_description" AS department_description,
    "other_details" AS other_details
FROM Departments;
DROP VIEW IF EXISTS "degree_programs_info";
CREATE VIEW degree_programs_info AS
SELECT
    "degree_program_id" AS degree_program_id,
    "department_id" AS department_id,
    "degree_summary_name" AS degree_summary_name,
    "degree_summary_description" AS degree_summary_description,
    "other_details" AS other_details
FROM Degree_Programs;
DROP VIEW IF EXISTS "course_sections";
CREATE VIEW course_sections AS
SELECT
    "section_id" AS section_id,
    "course_id" AS course_id,
    "section_name" AS section_name,
    "section_description" AS section_description,
    "other_details" AS other_details
FROM Sections;
DROP VIEW IF EXISTS "academic_semesters";
CREATE VIEW academic_semesters AS
SELECT
    "semester_id" AS semester_id,
    "semester_name" AS semester_name,
    "semester_description" AS semester_description,
    "other_details" AS other_details
FROM Semesters;
DROP VIEW IF EXISTS "university_students";
CREATE VIEW university_students AS
SELECT
    "student_id" AS student_id,
    "current_address_id" AS current_address_id,
    "permanent_address_id" AS permanent_address_id,
    "first_name" AS first_name,
    "middle_name" AS middle_name,
    "last_name" AS last_name,
    "cell_mobile_number" AS cell_mobile_number,
    "email_address" AS email_address,
    "ssn" AS ssn,
    "date_first_registered" AS date_first_registered,
    "date_left" AS date_left,
    "other_student_details" AS other_student_details
FROM Students;
DROP VIEW IF EXISTS "student_enrollments";
CREATE VIEW student_enrollments AS
SELECT
    "student_enrolment_id" AS student_enrolment_id,
    "degree_program_id" AS degree_program_id,
    "semester_id" AS semester_id,
    "student_id" AS student_id,
    "other_details" AS other_details
FROM Student_Enrolment;
DROP VIEW IF EXISTS "student_enrolled_courses";
CREATE VIEW student_enrolled_courses AS
SELECT
    "student_course_id" AS student_course_id,
    "course_id" AS course_id,
    "student_enrolment_id" AS student_enrolment_id
FROM Student_Enrolment_Courses;
DROP VIEW IF EXISTS "student_transcripts";
CREATE VIEW student_transcripts AS
SELECT
    "transcript_id" AS transcript_id,
    "transcript_date" AS transcript_date,
    "other_details" AS other_details
FROM Transcripts;
DROP VIEW IF EXISTS "transcript_contents_info";
CREATE VIEW transcript_contents_info AS
SELECT
    "student_course_id" AS student_course_id,
    "transcript_id" AS transcript_id
FROM Transcript_Contents;
DROP VIEW IF EXISTS "dog_breeds";
CREATE VIEW dog_breeds AS
SELECT
    "breed_code" AS breed_code,
    "breed_name" AS breed_name
FROM Breeds;
DROP VIEW IF EXISTS "vet_charges";
CREATE VIEW vet_charges AS
SELECT
    "charge_id" AS charge_id,
    "charge_type" AS charge_type,
    "charge_amount" AS charge_amount
FROM Charges;
DROP VIEW IF EXISTS "dog_sizes";
CREATE VIEW dog_sizes AS
SELECT
    "size_code" AS size_code,
    "size_description" AS size_description
FROM Sizes;
DROP VIEW IF EXISTS "vet_treatment_types";
CREATE VIEW vet_treatment_types AS
SELECT
    "treatment_type_code" AS treatment_type_code,
    "treatment_type_description" AS treatment_type_description
FROM Treatment_Types;
DROP VIEW IF EXISTS "dog_owners";
CREATE VIEW dog_owners AS
SELECT
    "owner_id" AS owner_id,
    "first_name" AS first_name,
    "last_name" AS last_name,
    "street" AS street,
    "city" AS city,
    "state" AS state,
    "zip_code" AS zip_code,
    "email_address" AS email_address,
    "home_phone" AS home_phone,
    "cell_number" AS cell_number
FROM Owners;
DROP VIEW IF EXISTS "vet_dogs";
CREATE VIEW vet_dogs AS
SELECT
    "dog_id" AS dog_id,
    "owner_id" AS owner_id,
    "abandoned_yn" AS abandoned_yn,
    "breed_code" AS breed_code,
    "size_code" AS size_code,
    "name" AS name,
    "age" AS age,
    "date_of_birth" AS date_of_birth,
    "gender" AS gender,
    "weight" AS weight,
    "date_arrived" AS date_arrived,
    "date_adopted" AS date_adopted,
    "date_departed" AS date_departed
FROM Dogs;
DROP VIEW IF EXISTS "vet_professionals";
CREATE VIEW vet_professionals AS
SELECT
    "professional_id" AS professional_id,
    "role_code" AS role_code,
    "first_name" AS first_name,
    "street" AS street,
    "city" AS city,
    "state" AS state,
    "zip_code" AS zip_code,
    "last_name" AS last_name,
    "email_address" AS email_address,
    "home_phone" AS home_phone,
    "cell_number" AS cell_number
FROM Professionals;
DROP VIEW IF EXISTS "vet_treatments";
CREATE VIEW vet_treatments AS
SELECT
    "treatment_id" AS treatment_id,
    "dog_id" AS dog_id,
    "professional_id" AS professional_id,
    "treatment_type_code" AS treatment_type_code,
    "date_of_treatment" AS date_of_treatment,
    "cost_of_treatment" AS cost_of_treatment
FROM Treatments;
DROP VIEW IF EXISTS "pet_students";
CREATE VIEW pet_students AS
SELECT
    "StuID" AS student_id,
    "LName" AS last_name,
    "Fname" AS first_name,
    "Age" AS age,
    "Sex" AS sex,
    "Major" AS major,
    "Advisor" AS advisor,
    "city_code" AS city_code
FROM Student;
DROP VIEW IF EXISTS "student_has_pet";
CREATE VIEW student_has_pet AS
SELECT
    "StuID" AS student_id,
    "PetID" AS pet_id
FROM Has_Pet;
DROP VIEW IF EXISTS "student_pets";
CREATE VIEW student_pets AS
SELECT
    "PetID" AS pet_id,
    "PetType" AS pet_type,
    "pet_age" AS pet_age,
    "weight" AS weight
FROM Pets;
DROP VIEW IF EXISTS "shop_employees";
CREATE VIEW shop_employees AS
SELECT
    "Employee_ID" AS employee_id,
    "Name" AS name,
    "Age" AS age,
    "City" AS city
FROM employee;
DROP VIEW IF EXISTS "retail_shops";
CREATE VIEW retail_shops AS
SELECT
    "Shop_ID" AS shop_id,
    "Name" AS name,
    "Location" AS location,
    "District" AS district,
    "Number_products" AS number_products,
    "Manager_name" AS manager_name
FROM shop;
DROP VIEW IF EXISTS "shop_hiring";
CREATE VIEW shop_hiring AS
SELECT
    "Shop_ID" AS shop_id,
    "Employee_ID" AS employee_id,
    "Start_from" AS start_from,
    "Is_full_time" AS is_full_time
FROM hiring;
DROP VIEW IF EXISTS "employee_evaluations";
CREATE VIEW employee_evaluations AS
SELECT
    "Employee_ID" AS employee_id,
    "Year_awarded" AS year_awarded,
    "Bonus" AS bonus
FROM evaluation;
DROP VIEW IF EXISTS "state_area_codes";
CREATE VIEW state_area_codes AS
SELECT
    "area_code" AS area_code,
    "state" AS state
FROM AREA_CODE_STATE;
DROP VIEW IF EXISTS "voting_contestants";
CREATE VIEW voting_contestants AS
SELECT
    "contestant_number" AS contestant_number,
    "contestant_name" AS contestant_name
FROM CONTESTANTS;
DROP VIEW IF EXISTS "contestant_votes";
CREATE VIEW contestant_votes AS
SELECT
    "vote_id" AS vote_id,
    "phone_number" AS phone_number,
    "state" AS state,
    "contestant_number" AS contestant_number,
    "created" AS created
FROM VOTES;
DROP VIEW IF EXISTS "stadiums";
CREATE VIEW stadiums AS
SELECT
    "Stadium_ID" AS stadium_id,
    "Location" AS location,
    "Name" AS name,
    "Capacity" AS capacity,
    "Highest" AS highest,
    "Lowest" AS lowest,
    "Average" AS average
FROM stadium;
DROP VIEW IF EXISTS "singers";
CREATE VIEW singers AS
SELECT
    "Singer_ID" AS singer_id,
    "Name" AS name,
    "Country" AS country,
    "Song_Name" AS song_name,
    "Song_release_year" AS song_release_year,
    "Age" AS age,
    "Is_male" AS is_male
FROM singer;
DROP VIEW IF EXISTS "concerts";
CREATE VIEW concerts AS
SELECT
    "concert_ID" AS concert_id,
    "concert_Name" AS concert_name,
    "Theme" AS theme,
    "Stadium_ID" AS stadium_id,
    "Year" AS year
FROM concert;
DROP VIEW IF EXISTS "concert_singers";
CREATE VIEW concert_singers AS
SELECT
    "concert_ID" AS concert_id,
    "Singer_ID" AS singer_id
FROM singer_in_concert;
DROP VIEW IF EXISTS "museums";
CREATE VIEW museums AS
SELECT
    "Museum_ID" AS museum_id,
    "Name" AS name,
    "Num_of_Staff" AS num_of_staff,
    "Open_Year" AS open_year
FROM museum;
DROP VIEW IF EXISTS "museum_visitors";
CREATE VIEW museum_visitors AS
SELECT
    "ID" AS visitor_id,
    "Name" AS name,
    "Level_of_membership" AS level_of_membership,
    "Age" AS age
FROM visitor;
DROP VIEW IF EXISTS "museum_visits";
CREATE VIEW museum_visits AS
SELECT
    "Museum_ID" AS museum_id,
    "visitor_ID" AS visitor_id,
    "Num_of_Ticket" AS num_of_ticket,
    "Total_spent" AS total_spent
FROM visit;

-- ==== org_views (57) ===========================================
DROP VIEW IF EXISTS "cluster1_CARS_DATA_join_CAR_NAMES";
CREATE VIEW cluster1_CARS_DATA_join_CAR_NAMES AS 
SELECT CARS_DATA.Id, CARS_DATA.MPG, CARS_DATA.Cylinders, CARS_DATA.Edispl, CARS_DATA.Horsepower, CARS_DATA.Weight, CARS_DATA.Accelerate, CARS_DATA.Year, CAR_NAMES.MakeId, CAR_NAMES.Model, CAR_NAMES.Make 
FROM CARS_DATA JOIN CAR_NAMES ON CARS_DATA.Id = CAR_NAMES.MakeId;
DROP VIEW IF EXISTS "cluster2_concert_join_stadium";
CREATE VIEW cluster2_concert_join_stadium AS 
SELECT concert.concert_ID, concert.concert_Name, concert.Theme, concert.Stadium_ID AS concert_Stadium_ID, concert.Year, stadium.Stadium_ID AS stadium_Stadium_ID, stadium.Location, stadium.Name, stadium.Capacity, stadium.Highest, stadium.Lowest, stadium.Average 
FROM concert JOIN stadium ON concert.Stadium_ID = stadium.Stadium_ID;
DROP VIEW IF EXISTS "cluster3_Documents_join_Templates";
CREATE VIEW cluster3_Documents_join_Templates AS 
SELECT Documents.Document_ID, Documents.Template_ID AS Documents_Template_ID, Documents.Document_Name, Documents.Document_Description, Documents.Other_Details, Templates.Template_ID AS Templates_Template_ID, Templates.Version_Number, Templates.Template_Type_Code, Templates.Date_Effective_From, Templates.Date_Effective_To, Templates.Template_Details 
FROM Documents JOIN Templates ON Documents.Template_ID = Templates.Template_ID;
DROP VIEW IF EXISTS "cluster4_Dogs_join_Treatments";
CREATE VIEW cluster4_Dogs_join_Treatments AS 
SELECT Dogs.dog_id AS Dogs_dog_id, Dogs.owner_id, Dogs.abandoned_yn, Dogs.breed_code, Dogs.size_code, Dogs.name, Dogs.age, Dogs.date_of_birth, Dogs.gender, Dogs.weight, Dogs.date_arrived, Dogs.date_adopted, Dogs.date_departed, Treatments.treatment_id, Treatments.dog_id AS Treatments_dog_id, Treatments.professional_id, Treatments.treatment_type_code, Treatments.date_of_treatment, Treatments.cost_of_treatment 
FROM Dogs JOIN Treatments ON Dogs.dog_id = Treatments.dog_id;
DROP VIEW IF EXISTS "cluster5_Professionals_join_Treatments";
CREATE VIEW cluster5_Professionals_join_Treatments AS 
SELECT Professionals.professional_id AS Professionals_professional_id, Professionals.role_code, Professionals.first_name, Professionals.street, Professionals.city, Professionals.state, Professionals.zip_code, Professionals.last_name, Professionals.email_address, Professionals.home_phone, Professionals.cell_number, Treatments.treatment_id, Treatments.dog_id, Treatments.professional_id AS Treatments_professional_id, Treatments.treatment_type_code, Treatments.date_of_treatment, Treatments.cost_of_treatment 
FROM Professionals JOIN Treatments ON Professionals.professional_id = Treatments.professional_id;
DROP VIEW IF EXISTS "cluster6_Dogs_join_Owners";
CREATE VIEW cluster6_Dogs_join_Owners AS 
SELECT Dogs.dog_id, Dogs.owner_id AS Dogs_owner_id, Dogs.abandoned_yn, Dogs.breed_code, Dogs.size_code, Dogs.name, Dogs.age, Dogs.date_of_birth, Dogs.gender, Dogs.weight, Dogs.date_arrived, Dogs.date_adopted, Dogs.date_departed, Owners.owner_id AS Owners_owner_id, Owners.first_name, Owners.last_name, Owners.street, Owners.city, Owners.state, Owners.zip_code, Owners.email_address, Owners.home_phone, Owners.cell_number 
FROM Dogs JOIN Owners ON Dogs.owner_id = Owners.owner_id;
DROP VIEW IF EXISTS "cluster7_AIRLINES_join_FLIGHTS";
CREATE VIEW cluster7_AIRLINES_join_FLIGHTS AS 
SELECT airlines.uid, airlines.Airline AS airlines_Airline, airlines.Abbreviation, airlines.Country, flights.Airline AS flights_Airline, flights.FlightNo, flights.SourceAirport, flights.DestAirport 
FROM airlines JOIN flights ON airlines.uid = flights.Airline;
DROP VIEW IF EXISTS "cluster8_AIRPORTS_join_FLIGHTS";
CREATE VIEW cluster8_AIRPORTS_join_FLIGHTS AS 
SELECT airports.City, airports.AirportCode, airports.AirportName, airports.Country, airports.CountryAbbrev, flights.Airline, flights.FlightNo, flights.SourceAirport, flights.DestAirport 
FROM airports JOIN flights ON airports.AirportCode = flights.SourceAirport;
DROP VIEW IF EXISTS "cluster9_Friend_join_Highschooler";
CREATE VIEW cluster9_Friend_join_Highschooler AS 
SELECT Friend.student_id, Friend.friend_id, Highschooler.ID, Highschooler.name, Highschooler.grade 
FROM Friend JOIN Highschooler ON Friend.student_id = Highschooler.ID;
DROP VIEW IF EXISTS "cluster10_Highschooler_join_Likes";
CREATE VIEW cluster10_Highschooler_join_Likes AS 
SELECT Highschooler.ID, Highschooler.name, Highschooler.grade, Likes.student_id, Likes.liked_id 
FROM Highschooler JOIN Likes ON Highschooler.ID = Likes.student_id;
DROP VIEW IF EXISTS "cluster11_has_pet_join_student";
CREATE VIEW cluster11_has_pet_join_student AS 
SELECT Has_Pet.StuID AS Has_Pet_StuID, Has_Pet.PetID, Student.StuID AS Student_StuID, Student.LName, Student.Fname, Student.Age, Student.Sex, Student.Major, Student.Advisor, Student.city_code 
FROM Has_Pet JOIN Student ON Has_Pet.StuID = Student.StuID;
DROP VIEW IF EXISTS "cluster12_has_pet_join_pets_join_student";
CREATE VIEW cluster12_has_pet_join_pets_join_student AS 
SELECT Has_Pet.StuID AS Has_Pet_StuID, Has_Pet.PetID AS Has_Pet_PetID, Pets.PetID AS Pets_PetID, Pets.PetType, Pets.pet_age, Pets.weight, Student.StuID AS Student_StuID, Student.LName, Student.Fname, Student.Age, Student.Sex, Student.Major, Student.Advisor, Student.city_code 
FROM Has_Pet JOIN Pets ON Has_Pet.PetID = Pets.PetID JOIN Student ON Has_Pet.StuID = Student.StuID;
DROP VIEW IF EXISTS "cluster13_people_join_poker_player";
CREATE VIEW cluster13_people_join_poker_player AS 
SELECT people.People_ID AS people_People_ID, people.Nationality, people.Name, people.Birth_Date, people.Height, poker_player.Poker_Player_ID, poker_player.People_ID AS poker_player_People_ID, poker_player.Final_Table_Made, poker_player.Best_Finish, poker_player.Money_Rank, poker_player.Earnings 
FROM people JOIN poker_player ON people.People_ID = poker_player.People_ID;
DROP VIEW IF EXISTS "cluster14_TV_Channel_join_Cartoon";
CREATE VIEW cluster14_TV_Channel_join_Cartoon AS 
SELECT TV_Channel.id AS TV_Channel_id, TV_Channel.series_name, TV_Channel.Country, TV_Channel.Language, TV_Channel.Content, TV_Channel.Pixel_aspect_ratio_PAR, TV_Channel.Hight_definition_TV, TV_Channel.Pay_per_view_PPV, TV_Channel.Package_Option, Cartoon.id AS Cartoon_id, Cartoon.Title, Cartoon.Directed_by, Cartoon.Written_by, Cartoon.Original_air_date, Cartoon.Production_code, Cartoon.Channel 
FROM TV_Channel JOIN Cartoon ON TV_Channel.id = Cartoon.Channel;
DROP VIEW IF EXISTS "cluster15_country_join_countrylanguage";
CREATE VIEW cluster15_country_join_countrylanguage AS 
SELECT country.Code, country.Name, country.Continent, country.Region, country.SurfaceArea, country.IndepYear, country.Population, country.LifeExpectancy, country.GNP, country.GNPOld, country.LocalName, country.GovernmentForm, country.HeadOfState, country.Capital, country.Code2, countrylanguage.CountryCode, countrylanguage.Language, countrylanguage.IsOfficial, countrylanguage.Percentage 
FROM country JOIN countrylanguage ON country.Code = countrylanguage.CountryCode;
DROP VIEW IF EXISTS "cluster16_death";
CREATE VIEW cluster16_death AS 
SELECT death.caused_by_ship_id, death.id, death.note, death.killed, death.injured 
FROM death;
DROP VIEW IF EXISTS "cluster17_death_join_ship";
CREATE VIEW cluster17_death_join_ship AS 
SELECT death.caused_by_ship_id, death.id AS death_id, death.note, death.killed, death.injured, ship.lost_in_battle, ship.id AS ship_id, ship.name, ship.tonnage, ship.ship_type, ship.location, ship.disposition_of_ship 
FROM death JOIN ship ON death.caused_by_ship_id = ship.id;
DROP VIEW IF EXISTS "cluster18_battle";
CREATE VIEW cluster18_battle AS 
SELECT battle.id, battle.name, battle.date, battle.bulgarian_commander, battle.latin_commander, battle.result 
FROM battle;
DROP VIEW IF EXISTS "cluster19_CAR_MAKERS_join_COUNTRIES";
CREATE VIEW cluster19_CAR_MAKERS_join_COUNTRIES AS 
SELECT car_makers.Id, car_makers.Maker, car_makers.FullName, car_makers.Country, countries.CountryId, countries.CountryName, countries.Continent 
FROM car_makers JOIN countries ON car_makers.Country = countries.CountryId;
DROP VIEW IF EXISTS "cluster20_continents";
CREATE VIEW cluster20_continents AS 
SELECT continents.ContId, continents.Continent 
FROM continents;
DROP VIEW IF EXISTS "cluster21_CAR_MAKERS_join_MODEL_LIST";
CREATE VIEW cluster21_CAR_MAKERS_join_MODEL_LIST AS 
SELECT car_makers.Id, car_makers.Maker AS car_makers_Maker, car_makers.FullName, car_makers.Country, model_list.ModelId, model_list.Maker AS model_list_Maker, model_list.Model 
FROM car_makers JOIN model_list ON car_makers.Id = model_list.Maker;
DROP VIEW IF EXISTS "cluster22_singer";
CREATE VIEW cluster22_singer AS 
SELECT singer.Singer_ID, singer.Name, singer.Country, singer.Song_Name, singer.Song_release_year, singer.Age, singer.Is_male 
FROM singer;
DROP VIEW IF EXISTS "cluster23_concert_join_singer_in_concert";
CREATE VIEW cluster23_concert_join_singer_in_concert AS 
SELECT concert.concert_ID AS concert_concert_ID, concert.concert_Name, concert.Theme, concert.Stadium_ID, concert.Year, singer_in_concert.concert_ID AS singer_in_concert_concert_ID, singer_in_concert.Singer_ID 
FROM concert JOIN singer_in_concert ON concert.concert_ID = singer_in_concert.concert_ID;
DROP VIEW IF EXISTS "cluster24_teacher";
CREATE VIEW cluster24_teacher AS 
SELECT teacher.Teacher_ID, teacher.Name, teacher.Age, teacher.Hometown 
FROM teacher;
DROP VIEW IF EXISTS "cluster25_course_arrange_join_teacher";
CREATE VIEW cluster25_course_arrange_join_teacher AS 
SELECT course_arrange.Course_ID, course_arrange.Teacher_ID AS course_arrange_Teacher_ID, course_arrange.Grade, teacher.Teacher_ID AS teacher_Teacher_ID, teacher.Name, teacher.Age, teacher.Hometown 
FROM course_arrange JOIN teacher ON course_arrange.Teacher_ID = teacher.Teacher_ID;
DROP VIEW IF EXISTS "cluster26_course_join_course_arrange_join_teacher";
CREATE VIEW cluster26_course_join_course_arrange_join_teacher AS 
SELECT course.Course_ID AS course_Course_ID, course.Staring_Date, course.Course, course_arrange.Course_ID AS course_arrange_Course_ID, course_arrange.Teacher_ID AS course_arrange_Teacher_ID, course_arrange.Grade, teacher.Teacher_ID AS teacher_Teacher_ID, teacher.Name, teacher.Age, teacher.Hometown 
FROM course JOIN course_arrange ON course.Course_ID = course_arrange.Course_ID JOIN teacher ON course_arrange.Teacher_ID = teacher.Teacher_ID;
DROP VIEW IF EXISTS "cluster27_Documents_join_Paragraphs";
CREATE VIEW cluster27_Documents_join_Paragraphs AS 
SELECT Documents.Document_ID AS Documents_Document_ID, Documents.Template_ID, Documents.Document_Name, Documents.Document_Description, Documents.Other_Details AS Documents_Other_Details, Paragraphs.Paragraph_ID, Paragraphs.Document_ID AS Paragraphs_Document_ID, Paragraphs.Paragraph_Text, Paragraphs.Other_Details AS Paragraphs_Other_Details 
FROM Documents JOIN Paragraphs ON Documents.Document_ID = Paragraphs.Document_ID;
DROP VIEW IF EXISTS "cluster28_Ref_Template_Types";
CREATE VIEW cluster28_Ref_Template_Types AS 
SELECT Ref_Template_Types.Template_Type_Code, Ref_Template_Types.Template_Type_Description 
FROM Ref_Template_Types;
DROP VIEW IF EXISTS "cluster29_Treatment_Types_join_Treatments_join_Professionals";
CREATE VIEW cluster29_Treatment_Types_join_Treatments_join_Professionals AS 
SELECT Treatment_Types.treatment_type_code AS Treatment_Types_treatment_type_code, Treatment_Types.treatment_type_description, Treatments.treatment_id, Treatments.dog_id, Treatments.professional_id AS Treatments_professional_id, Treatments.treatment_type_code AS Treatments_treatment_type_code, Treatments.date_of_treatment, Treatments.cost_of_treatment, Professionals.professional_id AS Professionals_professional_id, Professionals.role_code, Professionals.first_name, Professionals.street, Professionals.city, Professionals.state, Professionals.zip_code, Professionals.last_name, Professionals.email_address, Professionals.home_phone, Professionals.cell_number 
FROM Treatment_Types JOIN Treatments ON Treatment_Types.treatment_type_code = Treatments.treatment_type_code JOIN Professionals ON Treatments.professional_id = Professionals.professional_id;
DROP VIEW IF EXISTS "cluster30_Breeds_join_Dogs";
CREATE VIEW cluster30_Breeds_join_Dogs AS 
SELECT Breeds.breed_code AS Breeds_breed_code, Breeds.breed_name, Dogs.dog_id, Dogs.owner_id, Dogs.abandoned_yn, Dogs.breed_code AS Dogs_breed_code, Dogs.size_code, Dogs.name, Dogs.age, Dogs.date_of_birth, Dogs.gender, Dogs.weight, Dogs.date_arrived, Dogs.date_adopted, Dogs.date_departed 
FROM Breeds JOIN Dogs ON Breeds.breed_code = Dogs.breed_code;
DROP VIEW IF EXISTS "cluster31_Charges";
CREATE VIEW cluster31_Charges AS 
SELECT Charges.charge_id, Charges.charge_type, Charges.charge_amount 
FROM Charges;
DROP VIEW IF EXISTS "cluster32_employee_join_evaluation";
CREATE VIEW cluster32_employee_join_evaluation AS 
SELECT employee.Employee_ID AS employee_Employee_ID, employee.Name, employee.Age, employee.City, evaluation.Employee_ID AS evaluation_Employee_ID, evaluation.Year_awarded, evaluation.Bonus 
FROM employee JOIN evaluation ON employee.Employee_ID = evaluation.Employee_ID;
DROP VIEW IF EXISTS "cluster33_hiring_join_shop";
CREATE VIEW cluster33_hiring_join_shop AS 
SELECT hiring.Shop_ID AS hiring_Shop_ID, hiring.Employee_ID, hiring.Start_from, hiring.Is_full_time, shop.Shop_ID AS shop_Shop_ID, shop.Name, shop.Location, shop.District, shop.Number_products, shop.Manager_name 
FROM hiring JOIN shop ON hiring.Shop_ID = shop.Shop_ID;
DROP VIEW IF EXISTS "cluster34_visit_join_visitor";
CREATE VIEW cluster34_visit_join_visitor AS 
SELECT visit.Museum_ID, visit.visitor_ID, visit.Num_of_Ticket, visit.Total_spent, visitor.ID, visitor.Name, visitor.Level_of_membership, visitor.Age 
FROM visit JOIN visitor ON visit.visitor_ID = visitor.ID;
DROP VIEW IF EXISTS "cluster35_museum";
CREATE VIEW cluster35_museum AS 
SELECT museum.Museum_ID, museum.Name, museum.Num_of_Staff, museum.Open_Year 
FROM museum;
DROP VIEW IF EXISTS "cluster36_orchestra";
CREATE VIEW cluster36_orchestra AS 
SELECT orchestra.Orchestra_ID, orchestra.Orchestra, orchestra.Conductor_ID, orchestra.Record_Company, orchestra.Year_of_Founded, orchestra.Major_Record_Format 
FROM orchestra;
DROP VIEW IF EXISTS "cluster37_show";
CREATE VIEW cluster37_show AS 
SELECT show.Show_ID, show.Performance_ID, show.If_first_show, show.Result, show.Attendance 
FROM show;
DROP VIEW IF EXISTS "cluster38_conductor_join_orchestra";
CREATE VIEW cluster38_conductor_join_orchestra AS 
SELECT conductor.Conductor_ID AS conductor_Conductor_ID, conductor.Name, conductor.Age, conductor.Nationality, conductor.Year_of_Work, orchestra.Orchestra_ID, orchestra.Orchestra, orchestra.Conductor_ID AS orchestra_Conductor_ID, orchestra.Record_Company, orchestra.Year_of_Founded, orchestra.Major_Record_Format 
FROM conductor JOIN orchestra ON conductor.Conductor_ID = orchestra.Conductor_ID;
DROP VIEW IF EXISTS "cluster39_orchestra_join_performance";
CREATE VIEW cluster39_orchestra_join_performance AS 
SELECT orchestra.Orchestra_ID AS orchestra_Orchestra_ID, orchestra.Orchestra, orchestra.Conductor_ID, orchestra.Record_Company, orchestra.Year_of_Founded, orchestra.Major_Record_Format, performance.Performance_ID, performance.Orchestra_ID AS performance_Orchestra_ID, performance.Type, performance.Date, performance."Official_ratings_(millions)", performance.Weekly_rank, performance.Share 
FROM orchestra JOIN performance ON orchestra.Orchestra_ID = performance.Orchestra_ID;
DROP VIEW IF EXISTS "cluster40_Other_Available_Features_join_Ref_Feature_Types";
CREATE VIEW cluster40_Other_Available_Features_join_Ref_Feature_Types AS 
SELECT Other_Available_Features.feature_id, Other_Available_Features.feature_type_code AS Other_Available_Features_feature_type_code, Other_Available_Features.feature_name, Other_Available_Features.feature_description, Ref_Feature_Types.feature_type_code AS Ref_Feature_Types_feature_type_code, Ref_Feature_Types.feature_type_name 
FROM Other_Available_Features JOIN Ref_Feature_Types ON Other_Available_Features.feature_type_code = Ref_Feature_Types.feature_type_code;
DROP VIEW IF EXISTS "cluster41_Properties_join_Ref_Property_Types";
CREATE VIEW cluster41_Properties_join_Ref_Property_Types AS 
SELECT Properties.property_id, Properties.property_type_code AS Properties_property_type_code, Properties.date_on_market, Properties.date_sold, Properties.property_name, Properties.property_address, Properties.room_count, Properties.vendor_requested_price, Properties.buyer_offered_price, Properties.agreed_selling_price, Properties.apt_feature_1, Properties.apt_feature_2, Properties.apt_feature_3, Properties.fld_feature_1, Properties.fld_feature_2, Properties.fld_feature_3, Properties.hse_feature_1, Properties.hse_feature_2, Properties.hse_feature_3, Properties.oth_feature_1, Properties.oth_feature_2, Properties.oth_feature_3, Properties.shp_feature_1, Properties.shp_feature_2, Properties.shp_feature_3, Properties.other_property_details, Ref_Property_Types.property_type_code AS Ref_Property_Types_property_type_code, Ref_Property_Types.property_type_description 
FROM Properties JOIN Ref_Property_Types ON Properties.property_type_code = Ref_Property_Types.property_type_code;
DROP VIEW IF EXISTS "cluster42_Addresses";
CREATE VIEW cluster42_Addresses AS 
SELECT Addresses.address_id, Addresses.line_1, Addresses.line_2, Addresses.line_3, Addresses.city, Addresses.zip_postcode, Addresses.state_province_county, Addresses.country, Addresses.other_address_details 
FROM Addresses;
DROP VIEW IF EXISTS "cluster43_Semesters_join_Student_Enrolment";
CREATE VIEW cluster43_Semesters_join_Student_Enrolment AS 
SELECT Semesters.semester_id AS Semesters_semester_id, Semesters.semester_name, Semesters.semester_description, Semesters.other_details AS Semesters_other_details, Student_Enrolment.student_enrolment_id, Student_Enrolment.degree_program_id, Student_Enrolment.semester_id AS Student_Enrolment_semester_id, Student_Enrolment.student_id, Student_Enrolment.other_details AS Student_Enrolment_other_details 
FROM Semesters JOIN Student_Enrolment ON Semesters.semester_id = Student_Enrolment.semester_id;
DROP VIEW IF EXISTS "cluster44_Courses_join_Sections";
CREATE VIEW cluster44_Courses_join_Sections AS 
SELECT Courses.course_id AS Courses_course_id, Courses.course_name, Courses.course_description, Courses.other_details AS Courses_other_details, Sections.section_id, Sections.course_id AS Sections_course_id, Sections.section_name, Sections.section_description, Sections.other_details AS Sections_other_details 
FROM Courses JOIN Sections ON Courses.course_id = Sections.course_id;
DROP VIEW IF EXISTS "cluster45_Students";
CREATE VIEW cluster45_Students AS 
SELECT Students.student_id, Students.current_address_id, Students.permanent_address_id, Students.first_name, Students.middle_name, Students.last_name, Students.cell_mobile_number, Students.email_address, Students.ssn, Students.date_first_registered, Students.date_left, Students.other_student_details 
FROM Students;
DROP VIEW IF EXISTS "cluster46_Degree_Programs";
CREATE VIEW cluster46_Degree_Programs AS 
SELECT Degree_Programs.degree_program_id, Degree_Programs.department_id, Degree_Programs.degree_summary_name, Degree_Programs.degree_summary_description, Degree_Programs.other_details 
FROM Degree_Programs;
DROP VIEW IF EXISTS "cluster47_Transcript_Contents_join_Transcripts";
CREATE VIEW cluster47_Transcript_Contents_join_Transcripts AS 
SELECT Transcript_Contents.student_course_id, Transcript_Contents.transcript_id AS Transcript_Contents_transcript_id, Transcripts.transcript_id AS Transcripts_transcript_id, Transcripts.transcript_date, Transcripts.other_details 
FROM Transcript_Contents JOIN Transcripts ON Transcript_Contents.transcript_id = Transcripts.transcript_id;
DROP VIEW IF EXISTS "cluster48_Courses_join_Student_Enrolment_Courses";
CREATE VIEW cluster48_Courses_join_Student_Enrolment_Courses AS 
SELECT Courses.course_id AS Courses_course_id, Courses.course_name, Courses.course_description, Courses.other_details, Student_Enrolment_Courses.student_course_id, Student_Enrolment_Courses.course_id AS Student_Enrolment_Courses_course_id, Student_Enrolment_Courses.student_enrolment_id 
FROM Courses JOIN Student_Enrolment_Courses ON Courses.course_id = Student_Enrolment_Courses.course_id;
DROP VIEW IF EXISTS "cluster49_Degree_Programs_join_Departments";
CREATE VIEW cluster49_Degree_Programs_join_Departments AS 
SELECT Degree_Programs.degree_program_id, Degree_Programs.department_id AS Degree_Programs_department_id, Degree_Programs.degree_summary_name, Degree_Programs.degree_summary_description, Degree_Programs.other_details AS Degree_Programs_other_details, Departments.department_id AS Departments_department_id, Departments.department_name, Departments.department_description, Departments.other_details AS Departments_other_details 
FROM Degree_Programs JOIN Departments ON Degree_Programs.department_id = Departments.department_id;
DROP VIEW IF EXISTS "cluster50_Degree_Programs_join_Student_Enrolment_join_Students";
CREATE VIEW cluster50_Degree_Programs_join_Student_Enrolment_join_Students AS 
SELECT Degree_Programs.degree_program_id AS Degree_Programs_degree_program_id, Degree_Programs.department_id, Degree_Programs.degree_summary_name, Degree_Programs.degree_summary_description, Degree_Programs.other_details AS Degree_Programs_other_details, Student_Enrolment.student_enrolment_id, Student_Enrolment.degree_program_id AS Student_Enrolment_degree_program_id, Student_Enrolment.semester_id, Student_Enrolment.student_id AS Student_Enrolment_student_id, Student_Enrolment.other_details AS Student_Enrolment_other_details, Students.student_id AS Students_student_id, Students.current_address_id, Students.permanent_address_id, Students.first_name, Students.middle_name, Students.last_name, Students.cell_mobile_number, Students.email_address, Students.ssn, Students.date_first_registered, Students.date_left, Students.other_student_details 
FROM Degree_Programs JOIN Student_Enrolment ON Degree_Programs.degree_program_id = Student_Enrolment.degree_program_id JOIN Students ON Student_Enrolment.student_id = Students.student_id;
DROP VIEW IF EXISTS "cluster51_TV_series";
CREATE VIEW cluster51_TV_series AS 
SELECT TV_series.id, TV_series.Episode, TV_series.Air_Date, TV_series.Rating, TV_series.Share, TV_series."18_49_Rating_Share", TV_series.Viewers_m, TV_series.Weekly_Rank, TV_series.Channel 
FROM TV_series;
DROP VIEW IF EXISTS "cluster52_CONTESTANTS_join_VOTES";
CREATE VIEW cluster52_CONTESTANTS_join_VOTES AS 
SELECT CONTESTANTS.contestant_number AS CONTESTANTS_contestant_number, CONTESTANTS.contestant_name, VOTES.vote_id, VOTES.phone_number, VOTES.state, VOTES.contestant_number AS VOTES_contestant_number, VOTES.created 
FROM CONTESTANTS JOIN VOTES ON CONTESTANTS.contestant_number = VOTES.contestant_number;
DROP VIEW IF EXISTS "cluster53_AREA_CODE_STATE";
CREATE VIEW cluster53_AREA_CODE_STATE AS 
SELECT AREA_CODE_STATE.area_code, AREA_CODE_STATE.state 
FROM AREA_CODE_STATE;
DROP VIEW IF EXISTS "cluster54_city_join_country_join_countrylanguage";
CREATE VIEW cluster54_city_join_country_join_countrylanguage AS 
SELECT city.ID, city.Name AS city_Name, city.CountryCode AS city_CountryCode, city.District, city.Population AS city_Population, country.Code, country.Name AS country_Name, country.Continent, country.Region, country.SurfaceArea, country.IndepYear, country.Population AS country_Population, country.LifeExpectancy, country.GNP, country.GNPOld, country.LocalName, country.GovernmentForm, country.HeadOfState, country.Capital, country.Code2, countrylanguage.CountryCode AS countrylanguage_CountryCode, countrylanguage.Language, countrylanguage.IsOfficial, countrylanguage.Percentage 
FROM city JOIN country ON city.CountryCode = country.Code JOIN countrylanguage ON country.Code = countrylanguage.CountryCode;
DROP VIEW IF EXISTS "cluster55_players";
CREATE VIEW cluster55_players AS 
SELECT players.player_id, players.first_name, players.last_name, players.hand, players.birth_date, players.country_code 
FROM players;
DROP VIEW IF EXISTS "cluster56_matches";
CREATE VIEW cluster56_matches AS 
SELECT matches.best_of, matches.draw_size, matches.loser_age, matches.loser_entry, matches.loser_hand, matches.loser_ht, matches.loser_id, matches.loser_ioc, matches.loser_name, matches.loser_rank, matches.loser_rank_points, matches.loser_seed, matches.match_num, matches.minutes, matches.round, matches.score, matches.surface, matches.tourney_date, matches.tourney_id, matches.tourney_level, matches.tourney_name, matches.winner_age, matches.winner_entry, matches.winner_hand, matches.winner_ht, matches.winner_id, matches.winner_ioc, matches.winner_name, matches.winner_rank, matches.winner_rank_points, matches.winner_seed, matches.year 
FROM matches;
DROP VIEW IF EXISTS "cluster57_rankings";
CREATE VIEW cluster57_rankings AS 
SELECT rankings.ranking_date, rankings.ranking, rankings.player_id, rankings.ranking_points, rankings.tours 
FROM rankings;

-- ==== renamed_views (57) =======================================
DROP VIEW IF EXISTS "cluster1_car_data_join_car_make_names";
CREATE VIEW cluster1_car_data_join_car_make_names AS
SELECT car_data.make_id AS car_data_make_id, car_data.mpg, car_data.cylinders, car_data.edispl, car_data.horsepower, car_data.weight, car_data.accelerate, car_data.year, car_make_names.make_id AS car_make_names_make_id, car_make_names.model, car_make_names.make
FROM car_data JOIN car_make_names ON car_data.make_id = car_make_names.make_id;
DROP VIEW IF EXISTS "cluster2_car_countries_join_car_manufacturers";
CREATE VIEW cluster2_car_countries_join_car_manufacturers AS
SELECT car_countries.country_id, car_countries.country_name, car_countries.continent, car_manufacturers.maker_id, car_manufacturers.maker, car_manufacturers.full_name, car_manufacturers.country
FROM car_countries JOIN car_manufacturers ON car_countries.country_id = car_manufacturers.country;
DROP VIEW IF EXISTS "cluster3_car_manufacturers_join_car_models";
CREATE VIEW cluster3_car_manufacturers_join_car_models AS
SELECT car_manufacturers.maker_id AS car_manufacturers_maker_id, car_manufacturers.maker, car_manufacturers.full_name, car_manufacturers.country, car_models.model_id, car_models.maker_id AS car_models_maker_id, car_models.model
FROM car_manufacturers JOIN car_models ON car_manufacturers.maker_id = car_models.maker_id;
DROP VIEW IF EXISTS "cluster4_concerts_join_stadiums";
CREATE VIEW cluster4_concerts_join_stadiums AS
SELECT concerts.concert_id, concerts.concert_name, concerts.theme, concerts.stadium_id AS concerts_stadium_id, concerts.year, stadiums.stadium_id AS stadiums_stadium_id, stadiums.location, stadiums.name, stadiums.capacity, stadiums.highest, stadiums.lowest, stadiums.average
FROM concerts JOIN stadiums ON concerts.stadium_id = stadiums.stadium_id;
DROP VIEW IF EXISTS "cluster5_document_templates_join_managed_documents";
CREATE VIEW cluster5_document_templates_join_managed_documents AS
SELECT document_templates.template_id AS document_templates_template_id, document_templates.version_number, document_templates.template_type_code, document_templates.date_effective_from, document_templates.date_effective_to, document_templates.template_details, managed_documents.document_id, managed_documents.template_id AS managed_documents_template_id, managed_documents.document_name, managed_documents.document_description, managed_documents.other_details
FROM document_templates JOIN managed_documents ON document_templates.template_id = managed_documents.template_id;
DROP VIEW IF EXISTS "cluster6_vet_dogs_join_vet_treatments";
CREATE VIEW cluster6_vet_dogs_join_vet_treatments AS
SELECT vet_dogs.dog_id AS vet_dogs_dog_id, vet_dogs.owner_id, vet_dogs.abandoned_yn, vet_dogs.breed_code, vet_dogs.size_code, vet_dogs.name, vet_dogs.age, vet_dogs.date_of_birth, vet_dogs.gender, vet_dogs.weight, vet_dogs.date_arrived, vet_dogs.date_adopted, vet_dogs.date_departed, vet_treatments.treatment_id, vet_treatments.dog_id AS vet_treatments_dog_id, vet_treatments.professional_id, vet_treatments.treatment_type_code, vet_treatments.date_of_treatment, vet_treatments.cost_of_treatment
FROM vet_dogs JOIN vet_treatments ON vet_dogs.dog_id = vet_treatments.dog_id;
DROP VIEW IF EXISTS "cluster7_vet_professionals_join_vet_treatments";
CREATE VIEW cluster7_vet_professionals_join_vet_treatments AS
SELECT vet_professionals.professional_id AS vet_professionals_professional_id, vet_professionals.role_code, vet_professionals.first_name, vet_professionals.street, vet_professionals.city, vet_professionals.state, vet_professionals.zip_code, vet_professionals.last_name, vet_professionals.email_address, vet_professionals.home_phone, vet_professionals.cell_number, vet_treatments.treatment_id, vet_treatments.dog_id, vet_treatments.professional_id AS vet_treatments_professional_id, vet_treatments.treatment_type_code, vet_treatments.date_of_treatment, vet_treatments.cost_of_treatment
FROM vet_professionals JOIN vet_treatments ON vet_professionals.professional_id = vet_treatments.professional_id;
DROP VIEW IF EXISTS "cluster8_dog_owners_join_vet_dogs";
CREATE VIEW cluster8_dog_owners_join_vet_dogs AS
SELECT dog_owners.owner_id AS dog_owners_owner_id, dog_owners.first_name, dog_owners.last_name, dog_owners.street, dog_owners.city, dog_owners.state, dog_owners.zip_code, dog_owners.email_address, dog_owners.home_phone, dog_owners.cell_number, vet_dogs.dog_id, vet_dogs.owner_id AS vet_dogs_owner_id, vet_dogs.abandoned_yn, vet_dogs.breed_code, vet_dogs.size_code, vet_dogs.name, vet_dogs.age, vet_dogs.date_of_birth, vet_dogs.gender, vet_dogs.weight, vet_dogs.date_arrived, vet_dogs.date_adopted, vet_dogs.date_departed
FROM dog_owners JOIN vet_dogs ON dog_owners.owner_id = vet_dogs.owner_id;
DROP VIEW IF EXISTS "cluster9_airline_companies_join_flight_schedules";
CREATE VIEW cluster9_airline_companies_join_flight_schedules AS
SELECT airline_companies.airline_id AS airline_companies_airline_id, airline_companies.airline_name, airline_companies.abbreviation, airline_companies.country, flight_schedules.airline_id AS flight_schedules_airline_id, flight_schedules.flight_number, flight_schedules.source_airport, flight_schedules.dest_airport
FROM airline_companies JOIN flight_schedules ON airline_companies.airline_id = flight_schedules.airline_id;
DROP VIEW IF EXISTS "cluster10_airport_locations_join_flight_schedules";
CREATE VIEW cluster10_airport_locations_join_flight_schedules AS
SELECT airport_locations.city, airport_locations.airport_code, airport_locations.airport_name, airport_locations.country, airport_locations.country_abbrev, flight_schedules.airline_id, flight_schedules.flight_number, flight_schedules.source_airport, flight_schedules.dest_airport
FROM airport_locations JOIN flight_schedules ON airport_locations.airport_code = flight_schedules.source_airport OR airport_locations.airport_code = flight_schedules.dest_airport;
DROP VIEW IF EXISTS "cluster11_friends_join_highschoolers";
CREATE VIEW cluster11_friends_join_highschoolers AS
SELECT friends.student_id AS friends_student_id, friends.friend_id, highschoolers.student_id AS highschoolers_student_id, highschoolers.name, highschoolers.grade
FROM friends JOIN highschoolers ON friends.student_id = highschoolers.student_id OR friends.friend_id = highschoolers.student_id;
DROP VIEW IF EXISTS "cluster12_highschoolers_join_student_likes";
CREATE VIEW cluster12_highschoolers_join_student_likes AS
SELECT highschoolers.student_id AS highschoolers_student_id, highschoolers.name, highschoolers.grade, student_likes.student_id AS student_likes_student_id, student_likes.liked_id
FROM highschoolers JOIN student_likes ON highschoolers.student_id = student_likes.student_id OR highschoolers.student_id = student_likes.liked_id;
DROP VIEW IF EXISTS "cluster13_pet_students_join_student_has_pet";
CREATE VIEW cluster13_pet_students_join_student_has_pet AS
SELECT pet_students.student_id AS pet_students_student_id, pet_students.last_name, pet_students.first_name, pet_students.age, pet_students.sex, pet_students.major, pet_students.advisor, pet_students.city_code, student_has_pet.student_id AS student_has_pet_student_id, student_has_pet.pet_id
FROM pet_students JOIN student_has_pet ON pet_students.student_id = student_has_pet.student_id;
DROP VIEW IF EXISTS "cluster14_pet_students_join_student_has_pet_join_student_pets";
CREATE VIEW cluster14_pet_students_join_student_has_pet_join_student_pets AS
SELECT pet_students.student_id AS pet_students_student_id, pet_students.last_name, pet_students.first_name, pet_students.age, pet_students.sex, pet_students.major, pet_students.advisor, pet_students.city_code, student_has_pet.student_id AS student_has_pet_student_id, student_has_pet.pet_id AS student_has_pet_pet_id, student_pets.pet_id AS student_pets_pet_id, student_pets.pet_type, student_pets.pet_age, student_pets.weight
FROM pet_students JOIN student_has_pet ON pet_students.student_id = student_has_pet.student_id JOIN student_pets ON student_has_pet.pet_id = student_pets.pet_id;
DROP VIEW IF EXISTS "cluster15_people_info_join_poker_players";
CREATE VIEW cluster15_people_info_join_poker_players AS
SELECT people_info.people_id AS people_info_people_id, people_info.nationality, people_info.name, people_info.birth_date, people_info.height, poker_players.poker_player_id, poker_players.people_id AS poker_players_people_id, poker_players.final_table_made, poker_players.best_finish, poker_players.money_rank, poker_players.earnings
FROM people_info JOIN poker_players ON people_info.people_id = poker_players.people_id;
DROP VIEW IF EXISTS "cluster16_cartoons_join_tv_channels";
CREATE VIEW cluster16_cartoons_join_tv_channels AS
SELECT cartoons.cartoon_id, cartoons.title, cartoons.directed_by, cartoons.written_by, cartoons.original_air_date, cartoons.production_code, cartoons.channel_id AS cartoons_channel_id, tv_channels.channel_id AS tv_channels_channel_id, tv_channels.series_name, tv_channels.country, tv_channels.language, tv_channels.content, tv_channels.pixel_aspect_ratio, tv_channels.high_definition_tv, tv_channels.pay_per_view, tv_channels.package_option
FROM cartoons JOIN tv_channels ON cartoons.channel_id = tv_channels.channel_id;
DROP VIEW IF EXISTS "cluster17_countries_info_join_country_languages";
CREATE VIEW cluster17_countries_info_join_country_languages AS
SELECT countries_info.country_code AS countries_info_country_code, countries_info.name, countries_info.continent, countries_info.region, countries_info.surface_area, countries_info.indep_year, countries_info.population, countries_info.life_expectancy, countries_info.gnp, countries_info.gnp_old, countries_info.local_name, countries_info.government_form, countries_info.head_of_state, countries_info.capital, countries_info.code2, country_languages.country_code AS country_languages_country_code, country_languages.language, country_languages.is_official, country_languages.percentage
FROM countries_info JOIN country_languages ON countries_info.country_code = country_languages.country_code;
DROP VIEW IF EXISTS "cluster18_deaths";
CREATE VIEW cluster18_deaths AS
SELECT deaths.caused_by_ship_id, deaths.death_id, deaths.note, deaths.killed, deaths.injured
FROM deaths;
DROP VIEW IF EXISTS "cluster19_deaths_join_ships";
CREATE VIEW cluster19_deaths_join_ships AS
SELECT deaths.caused_by_ship_id, deaths.death_id, deaths.note, deaths.killed, deaths.injured, ships.lost_in_battle_id, ships.ship_id, ships.name, ships.tonnage, ships.ship_type, ships.location, ships.disposition_of_ship
FROM deaths JOIN ships ON deaths.caused_by_ship_id = ships.ship_id;
DROP VIEW IF EXISTS "cluster20_battles";
CREATE VIEW cluster20_battles AS
SELECT battles.battle_id, battles.name, battles.date, battles.bulgarian_commander, battles.latin_commander, battles.result
FROM battles;
DROP VIEW IF EXISTS "cluster21_continent_info";
CREATE VIEW cluster21_continent_info AS
SELECT continent_info.cont_id, continent_info.continent
FROM continent_info;
DROP VIEW IF EXISTS "cluster22_singers";
CREATE VIEW cluster22_singers AS
SELECT singers.singer_id, singers.name, singers.country, singers.song_name, singers.song_release_year, singers.age, singers.is_male
FROM singers;
DROP VIEW IF EXISTS "cluster23_concert_singers_join_concerts";
CREATE VIEW cluster23_concert_singers_join_concerts AS
SELECT concert_singers.concert_id AS concert_singers_concert_id, concert_singers.singer_id, concerts.concert_id AS concerts_concert_id, concerts.concert_name, concerts.theme, concerts.stadium_id, concerts.year
FROM concert_singers JOIN concerts ON concert_singers.concert_id = concerts.concert_id;
DROP VIEW IF EXISTS "cluster24_teachers";
CREATE VIEW cluster24_teachers AS
SELECT teachers.teacher_id, teachers.name, teachers.age, teachers.hometown
FROM teachers;
DROP VIEW IF EXISTS "cluster25_course_arrangements_join_teachers";
CREATE VIEW cluster25_course_arrangements_join_teachers AS
SELECT course_arrangements.course_id, course_arrangements.teacher_id AS course_arrangements_teacher_id, course_arrangements.grade, teachers.teacher_id AS teachers_teacher_id, teachers.name, teachers.age, teachers.hometown
FROM course_arrangements JOIN teachers ON course_arrangements.teacher_id = teachers.teacher_id;
DROP VIEW IF EXISTS "cluster26_course_arrangements_join_courses_info_join_teachers";
CREATE VIEW cluster26_course_arrangements_join_courses_info_join_teachers AS
SELECT course_arrangements.course_id AS course_arrangements_course_id, course_arrangements.teacher_id AS course_arrangements_teacher_id, course_arrangements.grade, courses_info.course_id AS courses_info_course_id, courses_info.starting_date, courses_info.course_name, teachers.teacher_id AS teachers_teacher_id, teachers.name, teachers.age, teachers.hometown
FROM course_arrangements JOIN courses_info ON course_arrangements.course_id = courses_info.course_id JOIN teachers ON course_arrangements.teacher_id = teachers.teacher_id;
DROP VIEW IF EXISTS "cluster27_document_paragraphs_join_managed_documents";
CREATE VIEW cluster27_document_paragraphs_join_managed_documents AS
SELECT document_paragraphs.paragraph_id, document_paragraphs.document_id AS document_paragraphs_document_id, document_paragraphs.paragraph_text, document_paragraphs.other_details AS document_paragraphs_other_details, managed_documents.document_id AS managed_documents_document_id, managed_documents.template_id, managed_documents.document_name, managed_documents.document_description, managed_documents.other_details AS managed_documents_other_details
FROM document_paragraphs JOIN managed_documents ON document_paragraphs.document_id = managed_documents.document_id;
DROP VIEW IF EXISTS "cluster28_template_types";
CREATE VIEW cluster28_template_types AS
SELECT template_types.template_type_code, template_types.template_type_description
FROM template_types;
DROP VIEW IF EXISTS "cluster29_vet_professionals_join_vet_treatment_types_join_vet_treatments";
CREATE VIEW cluster29_vet_professionals_join_vet_treatment_types_join_vet_treatments AS
SELECT vet_professionals.professional_id AS vet_professionals_professional_id, vet_professionals.role_code, vet_professionals.first_name, vet_professionals.street, vet_professionals.city, vet_professionals.state, vet_professionals.zip_code, vet_professionals.last_name, vet_professionals.email_address, vet_professionals.home_phone, vet_professionals.cell_number, vet_treatment_types.treatment_type_code AS vet_treatment_types_treatment_type_code, vet_treatment_types.treatment_type_description, vet_treatments.treatment_id, vet_treatments.dog_id, vet_treatments.professional_id AS vet_treatments_professional_id, vet_treatments.treatment_type_code AS vet_treatments_treatment_type_code, vet_treatments.date_of_treatment, vet_treatments.cost_of_treatment
FROM vet_professionals JOIN vet_treatments ON vet_professionals.professional_id = vet_treatments.professional_id JOIN vet_treatment_types ON vet_treatments.treatment_type_code = vet_treatment_types.treatment_type_code;
DROP VIEW IF EXISTS "cluster30_dog_breeds_join_vet_dogs";
CREATE VIEW cluster30_dog_breeds_join_vet_dogs AS
SELECT dog_breeds.breed_code AS dog_breeds_breed_code, dog_breeds.breed_name, vet_dogs.dog_id, vet_dogs.owner_id, vet_dogs.abandoned_yn, vet_dogs.breed_code AS vet_dogs_breed_code, vet_dogs.size_code, vet_dogs.name, vet_dogs.age, vet_dogs.date_of_birth, vet_dogs.gender, vet_dogs.weight, vet_dogs.date_arrived, vet_dogs.date_adopted, vet_dogs.date_departed
FROM dog_breeds JOIN vet_dogs ON dog_breeds.breed_code = vet_dogs.breed_code;
DROP VIEW IF EXISTS "cluster31_vet_charges";
CREATE VIEW cluster31_vet_charges AS
SELECT vet_charges.charge_id, vet_charges.charge_type, vet_charges.charge_amount
FROM vet_charges;
DROP VIEW IF EXISTS "cluster32_employee_evaluations_join_shop_employees";
CREATE VIEW cluster32_employee_evaluations_join_shop_employees AS
SELECT employee_evaluations.employee_id AS employee_evaluations_employee_id, employee_evaluations.year_awarded, employee_evaluations.bonus, shop_employees.employee_id AS shop_employees_employee_id, shop_employees.name, shop_employees.age, shop_employees.city
FROM employee_evaluations JOIN shop_employees ON employee_evaluations.employee_id = shop_employees.employee_id;
DROP VIEW IF EXISTS "cluster33_retail_shops_join_shop_hiring";
CREATE VIEW cluster33_retail_shops_join_shop_hiring AS
SELECT retail_shops.shop_id AS retail_shops_shop_id, retail_shops.name, retail_shops.location, retail_shops.district, retail_shops.number_products, retail_shops.manager_name, shop_hiring.shop_id AS shop_hiring_shop_id, shop_hiring.employee_id, shop_hiring.start_from, shop_hiring.is_full_time
FROM retail_shops JOIN shop_hiring ON retail_shops.shop_id = shop_hiring.shop_id;
DROP VIEW IF EXISTS "cluster34_museum_visitors_join_museum_visits";
CREATE VIEW cluster34_museum_visitors_join_museum_visits AS
SELECT museum_visitors.visitor_id AS museum_visitors_visitor_id, museum_visitors.name, museum_visitors.level_of_membership, museum_visitors.age, museum_visits.museum_id, museum_visits.visitor_id AS museum_visits_visitor_id, museum_visits.num_of_ticket, museum_visits.total_spent
FROM museum_visitors JOIN museum_visits ON museum_visitors.visitor_id = museum_visits.visitor_id;
DROP VIEW IF EXISTS "cluster35_museums";
CREATE VIEW cluster35_museums AS
SELECT museums.museum_id, museums.name, museums.num_of_staff, museums.open_year
FROM museums;
DROP VIEW IF EXISTS "cluster36_orchestras";
CREATE VIEW cluster36_orchestras AS
SELECT orchestras.orchestra_id, orchestras.orchestra_name, orchestras.conductor_id, orchestras.record_company, orchestras.year_founded, orchestras.major_record_format
FROM orchestras;
DROP VIEW IF EXISTS "cluster37_shows";
CREATE VIEW cluster37_shows AS
SELECT shows.show_id, shows.performance_id, shows.is_first_show, shows.result, shows.attendance
FROM shows;
DROP VIEW IF EXISTS "cluster38_conductors_join_orchestras";
CREATE VIEW cluster38_conductors_join_orchestras AS
SELECT conductors.conductor_id AS conductors_conductor_id, conductors.name, conductors.age, conductors.nationality, conductors.years_of_work, orchestras.orchestra_id, orchestras.orchestra_name, orchestras.conductor_id AS orchestras_conductor_id, orchestras.record_company, orchestras.year_founded, orchestras.major_record_format
FROM conductors JOIN orchestras ON conductors.conductor_id = orchestras.conductor_id;
DROP VIEW IF EXISTS "cluster39_orchestras_join_performances";
CREATE VIEW cluster39_orchestras_join_performances AS
SELECT orchestras.orchestra_id AS orchestras_orchestra_id, orchestras.orchestra_name, orchestras.conductor_id, orchestras.record_company, orchestras.year_founded, orchestras.major_record_format, performances.performance_id, performances.orchestra_id AS performances_orchestra_id, performances.performance_type, performances.performance_date, performances.official_ratings_millions, performances.weekly_rank, performances.audience_share
FROM orchestras JOIN performances ON orchestras.orchestra_id = performances.orchestra_id;
DROP VIEW IF EXISTS "cluster40_available_features_join_feature_types";
CREATE VIEW cluster40_available_features_join_feature_types AS
SELECT available_features.feature_id, available_features.feature_type_code AS available_features_feature_type_code, available_features.feature_name, available_features.feature_description, feature_types.feature_type_code AS feature_types_feature_type_code, feature_types.feature_type_name
FROM available_features JOIN feature_types ON available_features.feature_type_code = feature_types.feature_type_code;
DROP VIEW IF EXISTS "cluster41_property_listings_join_property_types";
CREATE VIEW cluster41_property_listings_join_property_types AS
SELECT property_listings.property_id, property_listings.property_type_code AS property_listings_property_type_code, property_listings.date_on_market, property_listings.date_sold, property_listings.property_name, property_listings.property_address, property_listings.room_count, property_listings.vendor_requested_price, property_listings.buyer_offered_price, property_listings.agreed_selling_price, property_listings.apt_feature_1, property_listings.apt_feature_2, property_listings.apt_feature_3, property_listings.fld_feature_1, property_listings.fld_feature_2, property_listings.fld_feature_3, property_listings.hse_feature_1, property_listings.hse_feature_2, property_listings.hse_feature_3, property_listings.oth_feature_1, property_listings.oth_feature_2, property_listings.oth_feature_3, property_listings.shp_feature_1, property_listings.shp_feature_2, property_listings.shp_feature_3, property_listings.other_property_details, property_types.property_type_code AS property_types_property_type_code, property_types.property_type_description
FROM property_listings JOIN property_types ON property_listings.property_type_code = property_types.property_type_code;
DROP VIEW IF EXISTS "cluster42_student_addresses";
CREATE VIEW cluster42_student_addresses AS
SELECT student_addresses.address_id, student_addresses.line_1, student_addresses.line_2, student_addresses.line_3, student_addresses.city, student_addresses.zip_postcode, student_addresses.state_province_county, student_addresses.country, student_addresses.other_address_details
FROM student_addresses;
DROP VIEW IF EXISTS "cluster43_academic_semesters_join_student_enrollments";
CREATE VIEW cluster43_academic_semesters_join_student_enrollments AS
SELECT academic_semesters.semester_id AS academic_semesters_semester_id, academic_semesters.semester_name, academic_semesters.semester_description, academic_semesters.other_details AS academic_semesters_other_details, student_enrollments.student_enrolment_id, student_enrollments.degree_program_id, student_enrollments.semester_id AS student_enrollments_semester_id, student_enrollments.student_id, student_enrollments.other_details AS student_enrollments_other_details
FROM academic_semesters JOIN student_enrollments ON academic_semesters.semester_id = student_enrollments.semester_id;
DROP VIEW IF EXISTS "cluster44_course_sections_join_university_courses";
CREATE VIEW cluster44_course_sections_join_university_courses AS
SELECT course_sections.section_id, course_sections.course_id AS course_sections_course_id, course_sections.section_name, course_sections.section_description, course_sections.other_details AS course_sections_other_details, university_courses.course_id AS university_courses_course_id, university_courses.course_name, university_courses.course_description, university_courses.other_details AS university_courses_other_details
FROM course_sections JOIN university_courses ON course_sections.course_id = university_courses.course_id;
DROP VIEW IF EXISTS "cluster45_university_students";
CREATE VIEW cluster45_university_students AS
SELECT university_students.student_id, university_students.current_address_id, university_students.permanent_address_id, university_students.first_name, university_students.middle_name, university_students.last_name, university_students.cell_mobile_number, university_students.email_address, university_students.ssn, university_students.date_first_registered, university_students.date_left, university_students.other_student_details
FROM university_students;
DROP VIEW IF EXISTS "cluster46_degree_programs_info";
CREATE VIEW cluster46_degree_programs_info AS
SELECT degree_programs_info.degree_program_id, degree_programs_info.department_id, degree_programs_info.degree_summary_name, degree_programs_info.degree_summary_description, degree_programs_info.other_details
FROM degree_programs_info;
DROP VIEW IF EXISTS "cluster47_student_transcripts_join_transcript_contents_info";
CREATE VIEW cluster47_student_transcripts_join_transcript_contents_info AS
SELECT student_transcripts.transcript_id AS student_transcripts_transcript_id, student_transcripts.transcript_date, student_transcripts.other_details, transcript_contents_info.student_course_id, transcript_contents_info.transcript_id AS transcript_contents_info_transcript_id
FROM student_transcripts JOIN transcript_contents_info ON student_transcripts.transcript_id = transcript_contents_info.transcript_id;
DROP VIEW IF EXISTS "cluster48_student_enrolled_courses_join_university_courses";
CREATE VIEW cluster48_student_enrolled_courses_join_university_courses AS
SELECT student_enrolled_courses.student_course_id, student_enrolled_courses.course_id AS student_enrolled_courses_course_id, student_enrolled_courses.student_enrolment_id, university_courses.course_id AS university_courses_course_id, university_courses.course_name, university_courses.course_description, university_courses.other_details
FROM student_enrolled_courses JOIN university_courses ON student_enrolled_courses.course_id = university_courses.course_id;
DROP VIEW IF EXISTS "cluster49_degree_programs_info_join_university_departments";
CREATE VIEW cluster49_degree_programs_info_join_university_departments AS
SELECT degree_programs_info.degree_program_id, degree_programs_info.department_id AS degree_programs_info_department_id, degree_programs_info.degree_summary_name, degree_programs_info.degree_summary_description, degree_programs_info.other_details AS degree_programs_info_other_details, university_departments.department_id AS university_departments_department_id, university_departments.department_name, university_departments.department_description, university_departments.other_details AS university_departments_other_details
FROM degree_programs_info JOIN university_departments ON degree_programs_info.department_id = university_departments.department_id;
DROP VIEW IF EXISTS "cluster50_degree_programs_info_join_student_enrollments_join_university_students";
CREATE VIEW cluster50_degree_programs_info_join_student_enrollments_join_university_students AS
SELECT degree_programs_info.degree_program_id AS degree_programs_info_degree_program_id, degree_programs_info.department_id, degree_programs_info.degree_summary_name, degree_programs_info.degree_summary_description, degree_programs_info.other_details AS degree_programs_info_other_details, student_enrollments.student_enrolment_id, student_enrollments.degree_program_id AS student_enrollments_degree_program_id, student_enrollments.semester_id, student_enrollments.student_id AS student_enrollments_student_id, student_enrollments.other_details AS student_enrollments_other_details, university_students.student_id AS university_students_student_id, university_students.current_address_id, university_students.permanent_address_id, university_students.first_name, university_students.middle_name, university_students.last_name, university_students.cell_mobile_number, university_students.email_address, university_students.ssn, university_students.date_first_registered, university_students.date_left, university_students.other_student_details
FROM degree_programs_info JOIN student_enrollments ON degree_programs_info.degree_program_id = student_enrollments.degree_program_id JOIN university_students ON student_enrollments.student_id = university_students.student_id;
DROP VIEW IF EXISTS "cluster51_tv_series_episodes";
CREATE VIEW cluster51_tv_series_episodes AS
SELECT tv_series_episodes.series_id, tv_series_episodes.episode, tv_series_episodes.air_date, tv_series_episodes.rating, tv_series_episodes.share, tv_series_episodes.rating_share_18_49, tv_series_episodes.viewers_millions, tv_series_episodes.weekly_rank, tv_series_episodes.channel_id
FROM tv_series_episodes;
DROP VIEW IF EXISTS "cluster52_contestant_votes_join_voting_contestants";
CREATE VIEW cluster52_contestant_votes_join_voting_contestants AS
SELECT contestant_votes.vote_id, contestant_votes.phone_number, contestant_votes.state, contestant_votes.contestant_number AS contestant_votes_contestant_number, contestant_votes.created, voting_contestants.contestant_number AS voting_contestants_contestant_number, voting_contestants.contestant_name
FROM contestant_votes JOIN voting_contestants ON contestant_votes.contestant_number = voting_contestants.contestant_number;
DROP VIEW IF EXISTS "cluster53_state_area_codes";
CREATE VIEW cluster53_state_area_codes AS
SELECT state_area_codes.area_code, state_area_codes.state
FROM state_area_codes;
DROP VIEW IF EXISTS "cluster54_cities_join_countries_info_join_country_languages";
CREATE VIEW cluster54_cities_join_countries_info_join_country_languages AS
SELECT cities.city_id, cities.name AS cities_name, cities.country_code AS cities_country_code, cities.district, cities.population AS cities_population, countries_info.country_code AS countries_info_country_code, countries_info.name AS countries_info_name, countries_info.continent, countries_info.region, countries_info.surface_area, countries_info.indep_year, countries_info.population AS countries_info_population, countries_info.life_expectancy, countries_info.gnp, countries_info.gnp_old, countries_info.local_name, countries_info.government_form, countries_info.head_of_state, countries_info.capital, countries_info.code2, country_languages.country_code AS country_languages_country_code, country_languages.language, country_languages.is_official, country_languages.percentage
FROM cities JOIN countries_info ON cities.country_code = countries_info.country_code JOIN country_languages ON countries_info.country_code = country_languages.country_code;
DROP VIEW IF EXISTS "cluster55_tennis_players";
CREATE VIEW cluster55_tennis_players AS
SELECT tennis_players.player_id, tennis_players.first_name, tennis_players.last_name, tennis_players.hand, tennis_players.birth_date, tennis_players.country_code
FROM tennis_players;
DROP VIEW IF EXISTS "cluster56_tennis_matches";
CREATE VIEW cluster56_tennis_matches AS
SELECT tennis_matches.best_of, tennis_matches.draw_size, tennis_matches.loser_age, tennis_matches.loser_entry, tennis_matches.loser_hand, tennis_matches.loser_height, tennis_matches.loser_id, tennis_matches.loser_ioc, tennis_matches.loser_name, tennis_matches.loser_rank, tennis_matches.loser_rank_points, tennis_matches.loser_seed, tennis_matches.match_num, tennis_matches.minutes, tennis_matches.round, tennis_matches.score, tennis_matches.surface, tennis_matches.tourney_date, tennis_matches.tourney_id, tennis_matches.tourney_level, tennis_matches.tourney_name, tennis_matches.winner_age, tennis_matches.winner_entry, tennis_matches.winner_hand, tennis_matches.winner_height, tennis_matches.winner_id, tennis_matches.winner_ioc, tennis_matches.winner_name, tennis_matches.winner_rank, tennis_matches.winner_rank_points, tennis_matches.winner_seed, tennis_matches.year
FROM tennis_matches;
DROP VIEW IF EXISTS "cluster57_tennis_rankings";
CREATE VIEW cluster57_tennis_rankings AS
SELECT tennis_rankings.ranking_date, tennis_rankings.ranking, tennis_rankings.player_id, tennis_rankings.ranking_points, tennis_rankings.tours
FROM tennis_rankings;
