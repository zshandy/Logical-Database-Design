-- Benchmark view layer for bird-Union.
-- Extracted from merged_bird.sqlite by create_database.py --dump_benchmark.
-- Replay onto a merged base database with --recreate_benchmark.
-- Families are emitted in dependency order; the renamed cluster views read the
-- renamed table views, so they come last.


-- ==== renamed_tables (75) ======================================
DROP VIEW IF EXISTS "Bank_Accounts";
CREATE VIEW Bank_Accounts AS SELECT account_id, district_id, frequency AS statement_frequency, date AS account_creation_date FROM account;
DROP VIEW IF EXISTS "Bank_Cards";
CREATE VIEW Bank_Cards AS SELECT card_id, disp_id AS disposition_id, type AS card_tier, issued AS issued_date FROM card;
DROP VIEW IF EXISTS "Bank_Clients";
CREATE VIEW Bank_Clients AS SELECT client_id, gender, birth_date, district_id FROM client;
DROP VIEW IF EXISTS "Bank_Dispositions";
CREATE VIEW Bank_Dispositions AS SELECT disp_id AS disposition_id, client_id, account_id, type AS disposition_type FROM disp;
DROP VIEW IF EXISTS "Bank_Districts";
CREATE VIEW Bank_Districts AS SELECT district_id, A2 AS district_name, A3 AS region_name, A4 AS population_count, A5 AS muni_under_500, A6 AS muni_500_1999, A7 AS muni_2000_9999, A8 AS muni_over_10000, A9 AS city_count, A10 AS ratio_urban_inhabitants, A11 AS average_salary, A12 AS unemployment_rate_95, A13 AS unemployment_rate_96, A14 AS entrepreneurs_per_1000, A15 AS crime_count_95, A16 AS crime_count_96 FROM district;
DROP VIEW IF EXISTS "Bank_Loans";
CREATE VIEW Bank_Loans AS SELECT loan_id, account_id, date AS loan_date, amount AS loan_amount, duration AS loan_duration_months, payments AS monthly_payment, status AS loan_status FROM loan;
DROP VIEW IF EXISTS "Bank_Orders";
CREATE VIEW Bank_Orders AS SELECT order_id, account_id, bank_to AS recipient_bank, account_to AS recipient_account, amount AS transfer_amount, k_symbol AS payment_type_code FROM "order";
DROP VIEW IF EXISTS "Bank_Transactions";
CREATE VIEW Bank_Transactions AS SELECT trans_id AS transaction_id, account_id, date AS transaction_date, type AS transaction_type, operation AS transaction_mode, amount AS transaction_amount, balance AS balance_after_trans, k_symbol AS constant_symbol, bank AS partner_bank, account AS partner_account FROM trans;
DROP VIEW IF EXISTS "Chem_Atoms";
CREATE VIEW Chem_Atoms AS SELECT atom_id, molecule_id, element AS element_symbol FROM atom;
DROP VIEW IF EXISTS "Chem_Bonds";
CREATE VIEW Chem_Bonds AS SELECT bond_id, molecule_id, bond_type AS bond_symbol FROM bond;
DROP VIEW IF EXISTS "Chem_Links";
CREATE VIEW Chem_Links AS SELECT atom_id AS atom_id_1, atom_id2 AS atom_id_2, bond_id FROM connected;
DROP VIEW IF EXISTS "Chem_Molecules";
CREATE VIEW Chem_Molecules AS SELECT molecule_id, label AS carcinogenic_flag FROM molecule;
DROP VIEW IF EXISTS "Club_Attendance";
CREATE VIEW Club_Attendance AS SELECT link_to_event, link_to_member FROM attendance;
DROP VIEW IF EXISTS "Club_Budgets";
CREATE VIEW Club_Budgets AS SELECT budget_id, category AS budget_category, spent AS amount_spent, remaining AS amount_remaining, amount AS budgeted_amount, event_status, link_to_event FROM budget;
DROP VIEW IF EXISTS "Club_Events";
CREATE VIEW Club_Events AS SELECT event_id, event_name, event_date, type AS event_type, notes AS event_notes, location AS event_location, status AS event_status FROM event;
DROP VIEW IF EXISTS "Club_Expenses";
CREATE VIEW Club_Expenses AS SELECT expense_id, expense_description, expense_date, cost, approved AS is_approved, link_to_member, link_to_budget FROM expense;
DROP VIEW IF EXISTS "Club_Income";
CREATE VIEW Club_Income AS SELECT income_id, date_received, amount, source, notes, link_to_member FROM income;
DROP VIEW IF EXISTS "Club_Majors";
CREATE VIEW Club_Majors AS SELECT major_id, major_name, department, college FROM major;
DROP VIEW IF EXISTS "Club_Members";
CREATE VIEW Club_Members AS SELECT member_id, first_name, last_name, email AS email_address, position AS club_role, t_shirt_size, phone AS phone_number, zip AS zip_code, link_to_major AS major_id FROM member;
DROP VIEW IF EXISTS "Club_Zips";
CREATE VIEW Club_Zips AS SELECT zip_code, type AS zip_type, city, county, state, short_state AS state_abbrev FROM zip_code;
DROP VIEW IF EXISTS "Education_Lunch_Aid";
CREATE VIEW Education_Lunch_Aid AS SELECT CDSCode AS school_cds_code, "Academic Year" AS academic_year, "County Code" AS county_code, "District Code" AS district_code, "School Code" AS school_code, "County Name" AS county_name, "District Name" AS district_name, "School Name" AS school_name, "District Type" AS district_type, "School Type" AS school_type, "Educational Option Type" AS educational_option_type, "NSLP Provision Status" AS nslp_provision_status, "Charter School (Y/N)" AS is_charter_school, "Charter School Number" AS charter_school_number, "Charter Funding Type" AS charter_funding_type, IRC AS irc_code, "Low Grade" AS grade_low, "High Grade" AS grade_high, "Enrollment (K-12)" AS enrollment_k12, "Free Meal Count (K-12)" AS free_meal_count_k12, "Percent (%) Eligible Free (K-12)" AS percent_eligible_free_k12, "FRPM Count (K-12)" AS frpm_count_k12, "Percent (%) Eligible FRPM (K-12)" AS percent_eligible_frpm_k12, "Enrollment (Ages 5-17)" AS enrollment_ages_5_17, "Free Meal Count (Ages 5-17)" AS free_meal_count_ages_5_17, "Percent (%) Eligible Free (Ages 5-17)" AS percent_eligible_free_ages_5_17, "FRPM Count (Ages 5-17)" AS frpm_count_ages_5_17, "Percent (%) Eligible FRPM (Ages 5-17)" AS percent_eligible_frpm_ages_5_17, "2013-14 CALPADS Fall 1 Certification Status" AS calpads_certification_status FROM frpm;
DROP VIEW IF EXISTS "Education_SAT_Stats";
CREATE VIEW Education_SAT_Stats AS SELECT cds AS school_cds_code, rtype AS record_type, sname AS school_name, dname AS district_name, cname AS county_name, enroll12 AS grade_12_enrollment, NumTstTakr AS total_test_takers, AvgScrRead AS avg_score_reading, AvgScrMath AS avg_score_math, AvgScrWrite AS avg_score_writing, NumGE1500 AS num_scores_ge_1500 FROM satscores;
DROP VIEW IF EXISTS "Education_Schools";
CREATE VIEW Education_Schools AS SELECT CDSCode AS school_cds_code, NCESDist AS nces_district_id, NCESSchool AS nces_school_id, StatusType AS school_status, County AS county_name, District AS district_name, School AS school_name, Street AS street_address, StreetAbr AS street_address_abbrev, City AS city, Zip AS zip_code, State AS state, MailStreet AS mailing_street, MailStrAbr AS mailing_street_abbrev, MailCity AS mailing_city, MailZip AS mailing_zip, MailState AS mailing_state, Phone AS phone_number, Ext AS phone_extension, Website AS website_url, OpenDate AS date_opened, ClosedDate AS date_closed, Charter AS is_charter_flag, CharterNum AS charter_number, FundingType AS funding_type, DOC AS district_ownership_code, DOCType AS district_ownership_type, SOC AS school_ownership_code, SOCType AS school_ownership_type, EdOpsCode AS ed_ops_code, EdOpsName AS ed_ops_name, EILCode AS eil_code, EILName AS eil_name, GSoffered AS grades_offered, GSserved AS grades_served, Virtual AS is_virtual_code, Magnet AS is_magnet_flag, Latitude AS latitude, Longitude AS longitude, AdmFName1 AS admin_first_name_1, AdmLName1 AS admin_last_name_1, AdmEmail1 AS admin_email_1, AdmFName2 AS admin_first_name_2, AdmLName2 AS admin_last_name_2, AdmEmail2 AS admin_email_2, AdmFName3 AS admin_first_name_3, AdmLName3 AS admin_last_name_3, AdmEmail3 AS admin_email_3, LastUpdate AS last_update_date FROM schools;
DROP VIEW IF EXISTS "Energy_Customers";
CREATE VIEW Energy_Customers AS SELECT CustomerID AS customer_id, Segment AS customer_segment, Currency AS currency_type FROM customers;
DROP VIEW IF EXISTS "Energy_Products";
CREATE VIEW Energy_Products AS SELECT ProductID AS product_id, Description AS product_description FROM products;
DROP VIEW IF EXISTS "Energy_Sales";
CREATE VIEW Energy_Sales AS SELECT TransactionID AS trans_id, Date AS trans_date, Time AS trans_time, CustomerID AS customer_id, CardID AS card_id, GasStationID AS station_id, ProductID AS product_id, Amount AS quantity, Price AS total_price FROM transactions_1k;
DROP VIEW IF EXISTS "Energy_Stations";
CREATE VIEW Energy_Stations AS SELECT GasStationID AS station_id, ChainID AS chain_id, Country AS country_code, Segment AS station_segment FROM gasstations;
DROP VIEW IF EXISTS "Energy_Usage";
CREATE VIEW Energy_Usage AS SELECT CustomerID AS customer_id, Date AS year_month_string, Consumption AS gas_consumption FROM yearmonth;
DROP VIEW IF EXISTS "F1_Constructor_Results";
CREATE VIEW F1_Constructor_Results AS SELECT constructorResultsId AS result_id, raceId AS race_id, constructorId AS constructor_id, points, status FROM constructorResults;
DROP VIEW IF EXISTS "F1_Constructor_Standings";
CREATE VIEW F1_Constructor_Standings AS SELECT constructorStandingsId AS standing_id, raceId AS race_id, constructorId AS constructor_id, points, position, positionText AS position_text, wins FROM constructorStandings;
DROP VIEW IF EXISTS "F1_Constructors";
CREATE VIEW F1_Constructors AS SELECT constructorId AS constructor_id, constructorRef AS constructor_ref, name AS constructor_name, nationality, url FROM constructors;
DROP VIEW IF EXISTS "F1_Driver_Standings";
CREATE VIEW F1_Driver_Standings AS SELECT driverStandingsId AS standing_id, raceId AS race_id, driverId AS driver_id, points, position, positionText AS position_text, wins FROM driverStandings;
DROP VIEW IF EXISTS "F1_Drivers";
CREATE VIEW F1_Drivers AS SELECT driverId AS driver_id, driverRef AS driver_ref, number AS driver_number, code AS driver_code, forename AS first_name, surname AS last_name, dob AS birth_date, nationality, url FROM drivers;
DROP VIEW IF EXISTS "F1_Lap_Times";
CREATE VIEW F1_Lap_Times AS SELECT raceId AS race_id, driverId AS driver_id, lap AS lap_number, position, time AS lap_time, milliseconds FROM lapTimes;
DROP VIEW IF EXISTS "F1_Pit_Stops";
CREATE VIEW F1_Pit_Stops AS SELECT raceId AS race_id, driverId AS driver_id, stop AS stop_number, lap AS lap_number, time AS pit_time, duration AS pit_duration, milliseconds FROM pitStops;
DROP VIEW IF EXISTS "F1_Qualifying";
CREATE VIEW F1_Qualifying AS SELECT qualifyId AS qualifying_id, raceId AS race_id, driverId AS driver_id, constructorId AS constructor_id, number AS car_number, position, q1, q2, q3 FROM qualifying;
DROP VIEW IF EXISTS "F1_Races";
CREATE VIEW F1_Races AS SELECT raceId AS race_id, year AS season_year, round AS round_number, circuitId AS circuit_id, name AS race_name, date AS race_date, time AS race_time, url FROM races;
DROP VIEW IF EXISTS "F1_Results";
CREATE VIEW F1_Results AS SELECT resultId AS result_id, raceId AS race_id, driverId AS driver_id, constructorId AS constructor_id, number AS car_number, grid AS start_position, position AS finish_position, positionText AS finish_position_text, positionOrder AS finish_order, points, laps AS laps_completed, time AS finish_time, milliseconds, fastestLap AS fastest_lap_number, rank AS fastest_lap_rank, fastestLapTime AS fastest_lap_time, fastestLapSpeed AS fastest_lap_speed, statusId AS status_id FROM results;
DROP VIEW IF EXISTS "F1_Seasons";
CREATE VIEW F1_Seasons AS SELECT year, url FROM seasons;
DROP VIEW IF EXISTS "F1_Status_Codes";
CREATE VIEW F1_Status_Codes AS SELECT statusId AS status_id, status AS status_text FROM status;
DROP VIEW IF EXISTS "F1_Tracks";
CREATE VIEW F1_Tracks AS SELECT circuitId AS circuit_id, circuitRef AS circuit_ref, name AS circuit_name, location, country, lat AS latitude, lng AS longitude, alt AS altitude, url FROM circuits;
DROP VIEW IF EXISTS "Forum_Badges";
CREATE VIEW Forum_Badges AS SELECT Id AS badge_id, UserId AS user_id, Name AS badge_name, Date AS awarded_at FROM badges;
DROP VIEW IF EXISTS "Forum_Comments";
CREATE VIEW Forum_Comments AS SELECT Id AS comment_id, PostId AS post_id, Score AS comment_score, Text AS comment_text, CreationDate AS created_at, UserId AS user_id, UserDisplayName AS user_name FROM comments;
DROP VIEW IF EXISTS "Forum_History";
CREATE VIEW Forum_History AS SELECT Id AS history_id, PostHistoryTypeId AS history_type_id, PostId AS post_id, RevisionGUID AS revision_id, CreationDate AS created_at, UserId AS user_id, Text AS content_text, Comment AS edit_comment, UserDisplayName AS user_name FROM postHistory;
DROP VIEW IF EXISTS "Forum_Links";
CREATE VIEW Forum_Links AS SELECT Id AS link_id, CreationDate AS created_at, PostId AS post_id, RelatedPostId AS related_post_id, LinkTypeId AS link_type_id FROM postLinks;
DROP VIEW IF EXISTS "Forum_Posts";
CREATE VIEW Forum_Posts AS SELECT Id AS post_id, PostTypeId AS post_type_id, AcceptedAnswerId AS accepted_answer_id, CreaionDate AS created_at, Score AS post_score, ViewCount AS view_count, Body AS post_content, OwnerUserId AS user_id, LasActivityDate AS last_activity_at, Title AS post_title, Tags AS post_tags, AnswerCount AS answer_count, CommentCount AS comment_count, FavoriteCount AS favorite_count, LastEditorUserId AS last_editor_id, LastEditDate AS last_edit_date, CommunityOwnedDate AS community_owned_date, ParentId AS parent_post_id, ClosedDate AS closed_at, OwnerDisplayName AS owner_name, LastEditorDisplayName AS last_editor_name FROM posts;
DROP VIEW IF EXISTS "Forum_Tags";
CREATE VIEW Forum_Tags AS SELECT Id AS tag_id, TagName AS tag_name, Count AS post_count, ExcerptPostId AS excerpt_post_id, WikiPostId AS wiki_post_id FROM tags;
DROP VIEW IF EXISTS "Forum_Users";
CREATE VIEW Forum_Users AS SELECT Id AS user_id, Reputation AS reputation_score, CreationDate AS account_created_at, DisplayName AS display_name, LastAccessDate AS last_access_at, WebsiteUrl AS website_url, Location AS user_location, AboutMe AS bio_text, Views AS profile_views, UpVotes AS total_up_votes, DownVotes AS total_down_votes, AccountId AS global_account_id, Age AS user_age, ProfileImageUrl AS profile_image_url FROM users;
DROP VIEW IF EXISTS "Forum_Votes";
CREATE VIEW Forum_Votes AS SELECT Id AS vote_id, PostId AS post_id, VoteTypeId AS vote_type_id, CreationDate AS vote_date, UserId AS user_id, BountyAmount AS bounty_amount FROM votes;
DROP VIEW IF EXISTS "Hero_Alignments";
CREATE VIEW Hero_Alignments AS SELECT id AS alignment_id, alignment FROM alignment;
DROP VIEW IF EXISTS "Hero_Attribute_Types";
CREATE VIEW Hero_Attribute_Types AS SELECT id AS attribute_id, attribute_name FROM attribute;
DROP VIEW IF EXISTS "Hero_Attributes";
CREATE VIEW Hero_Attributes AS SELECT hero_id, attribute_id, attribute_value FROM hero_attribute;
DROP VIEW IF EXISTS "Hero_Colors";
CREATE VIEW Hero_Colors AS SELECT id AS colour_id, colour FROM colour;
DROP VIEW IF EXISTS "Hero_Genders";
CREATE VIEW Hero_Genders AS SELECT id AS gender_id, gender FROM gender;
DROP VIEW IF EXISTS "Hero_Power_Map";
CREATE VIEW Hero_Power_Map AS SELECT hero_id, power_id FROM hero_power;
DROP VIEW IF EXISTS "Hero_Profiles";
CREATE VIEW Hero_Profiles AS SELECT id AS hero_id, superhero_name, full_name, gender_id, eye_colour_id, hair_colour_id, skin_colour_id, race_id, publisher_id, alignment_id, height_cm, weight_kg FROM superhero;
DROP VIEW IF EXISTS "Hero_Publishers";
CREATE VIEW Hero_Publishers AS SELECT id AS publisher_id, publisher_name FROM publisher;
DROP VIEW IF EXISTS "Hero_Races";
CREATE VIEW Hero_Races AS SELECT id AS race_id, race FROM race;
DROP VIEW IF EXISTS "Hero_Superpowers";
CREATE VIEW Hero_Superpowers AS SELECT id AS superpower_id, power_name FROM superpower;
DROP VIEW IF EXISTS "MTG_Card_Foreign_Data";
CREATE VIEW MTG_Card_Foreign_Data AS SELECT id AS foreign_data_id, flavorText AS flavor_text, language, multiverseid AS multiverse_id, name AS card_name, text AS rules_text, type AS card_type, uuid FROM foreign_data;
DROP VIEW IF EXISTS "MTG_Cards";
CREATE VIEW MTG_Cards AS SELECT id AS card_id, artist AS illustrator_name, asciiName AS ascii_name, availability, borderColor AS border_color, cardKingdomFoilId, cardKingdomId, colorIdentity, colorIndicator, colors, convertedManaCost AS mana_cost, duelDeck AS duel_deck_id, edhrecRank AS edhrec_rank, faceConvertedManaCost, faceName, flavorName, flavorText, frameEffects, frameVersion, hand AS hand_modifier, hasAlternativeDeckLimit, hasContentWarning, hasFoil AS is_foil, hasNonFoil, isAlternative, isFullArt AS is_full_art, isOnlineOnly, isOversized, isPromo AS is_promo, isReprint AS is_reprint, isReserved, isStarter, isStorySpotlight AS is_story_spotlight, isTextless AS is_textless, isTimeshifted, keywords, layout, leadershipSkills, life AS life_modifier, loyalty, manaCost AS mana_cost_code, mcmId, mcmMetaId, mtgArenaId, mtgjsonV4Id, mtgoFoilId, mtgoId, multiverseId, name AS card_name, number AS collector_number, originalReleaseDate AS release_date, originalText AS original_rules, originalType AS original_type_line, otherFaceIds, power, printings, promoTypes AS promo_type, purchaseUrls, rarity, scryfallId, scryfallIllustrationId, scryfallOracleId, setCode AS set_code, side, subtypes, supertypes, tcgplayerProductId, text AS rules_text, toughness, type AS full_type_line, types AS main_type, uuid AS card_uuid, variations, watermark FROM cards;
DROP VIEW IF EXISTS "MTG_Legality";
CREATE VIEW MTG_Legality AS SELECT id AS legality_id, format, status AS legality_status, uuid FROM legalities;
DROP VIEW IF EXISTS "MTG_Rulings";
CREATE VIEW MTG_Rulings AS SELECT id AS ruling_id, date AS ruling_date, text AS ruling_text, uuid FROM rulings;
DROP VIEW IF EXISTS "MTG_Set_Translations";
CREATE VIEW MTG_Set_Translations AS SELECT id AS translation_id, language, setCode AS set_code, translation FROM set_translations;
DROP VIEW IF EXISTS "MTG_Sets";
CREATE VIEW MTG_Sets AS SELECT id AS set_id, baseSetSize AS base_set_size, block, booster, code AS set_code, isFoilOnly AS is_foil_only, isForeignOnly AS is_foreign_only, isNonFoilOnly AS is_nonfoil_only, isOnlineOnly AS is_online_only, isPartialPreview AS is_partial_preview, keyruneCode AS keyrune_code, mcmId AS mcm_id, mcmIdExtras AS mcm_id_extras, mcmName AS mcm_name, mtgoCode AS mtgo_code, name AS set_name, parentCode AS parent_set_code, releaseDate AS release_date, tcgplayerGroupId AS tcgplayer_group_id, totalSetSize AS total_set_size, type AS set_type FROM sets;
DROP VIEW IF EXISTS "Medical_Exams";
CREATE VIEW Medical_Exams AS SELECT ID AS patient_id, "Examination Date" AS exam_date, "aCL IgG" AS acl_igg, "aCL IgM" AS acl_igm, ANA AS ana_result, "ANA Pattern" AS ana_pattern, "aCL IgA" AS acl_iga, Diagnosis AS exam_diagnosis, KCT AS coagulation_kct, RVVT AS coagulation_rvvt, LAC AS lupus_anticoagulant, Symptoms AS physical_symptoms, Thrombosis AS thrombosis_severity FROM Examination;
DROP VIEW IF EXISTS "Medical_Lab_Results";
CREATE VIEW Medical_Lab_Results AS SELECT ID AS patient_id, Date AS test_date, GOT AS aspartate_aminotransferase_got, GPT AS alanine_aminotransferase_gpt, LDH AS lactate_dehydrogenase, ALP AS alkaline_phosphatase, TP AS total_protein, ALB AS albumin, UA AS uric_acid, UN AS urea_nitrogen, CRE AS creatinine, "T-BIL" AS total_bilirubin, "T-CHO" AS total_cholesterol, TG AS triglycerides, CPK AS creatine_phosphokinase, GLU AS blood_glucose, WBC AS white_blood_cell, RBC AS red_blood_cell, HGB AS hemoglobin, HCT AS hematocrit, PLT AS platelet_count, PT AS prothrombin_time, APTT AS partial_thromboplastin_time, FG AS fibrinogen, PIC AS plasmin_inhibitor, TAT AS thrombin_antithrombin, TAT2 AS thrombin_antithrombin_2, "U-PRO" AS urine_protein, IGG AS immunoglobulin_g, IGA AS immunoglobulin_a, IGM AS immunoglobulin_m, CRP AS c_reactive_protein, RA AS rheumatoid_arthritis, RF AS rheumatoid_factor, C3 AS complement_3, C4 AS complement_4, RNP AS anti_ribonuclear, SM AS anti_smith, SC170 AS anti_scl_70, SSA AS anti_ssa, SSB AS anti_ssb, CENTROMEA AS anti_centromere, DNA AS dna_antibody, "DNA-II" AS dna_antibody_2 FROM Laboratory;
DROP VIEW IF EXISTS "Medical_Patients";
CREATE VIEW Medical_Patients AS SELECT ID AS patient_id, SEX AS gender, Birthday AS birth_date, Description AS hospital_entry_date, `First Date` AS first_visit_date, Admission AS is_inpatient_flag, Diagnosis AS primary_diagnosis FROM Patient;
DROP VIEW IF EXISTS "Soccer_Countries";
CREATE VIEW Soccer_Countries AS SELECT id AS country_id, name AS country_name FROM Country;
DROP VIEW IF EXISTS "Soccer_Leagues";
CREATE VIEW Soccer_Leagues AS SELECT id AS league_id, country_id, name AS league_name FROM League;
DROP VIEW IF EXISTS "Soccer_Matches";
CREATE VIEW Soccer_Matches AS SELECT id AS match_internal_id, country_id, league_id, season, stage, date AS match_date, match_api_id, home_team_api_id, away_team_api_id, home_team_goal, away_team_goal, home_player_X1, home_player_X2, home_player_X3, home_player_X4, home_player_X5, home_player_X6, home_player_X7, home_player_X8, home_player_X9, home_player_X10, home_player_X11, away_player_X1, away_player_X2, away_player_X3, away_player_X4, away_player_X5, away_player_X6, away_player_X7, away_player_X8, away_player_X9, away_player_X10, away_player_X11, home_player_Y1, home_player_Y2, home_player_Y3, home_player_Y4, home_player_Y5, home_player_Y6, home_player_Y7, home_player_Y8, home_player_Y9, home_player_Y10, home_player_Y11, away_player_Y1, away_player_Y2, away_player_Y3, away_player_Y4, away_player_Y5, away_player_Y6, away_player_Y7, away_player_Y8, away_player_Y9, away_player_Y10, away_player_Y11, home_player_1, home_player_2, home_player_3, home_player_4, home_player_5, home_player_6, home_player_7, home_player_8, home_player_9, home_player_10, home_player_11, away_player_1, away_player_2, away_player_3, away_player_4, away_player_5, away_player_6, away_player_7, away_player_8, away_player_9, away_player_10, away_player_11, goal, shoton AS shots_on_target, shotoff AS shots_off_target, foulcommit AS fouls, card AS cards_events, "cross" AS crosses_events, corner AS corners_events, possession AS possession_stats, B365H, B365D, B365A, BWH, BWD, BWA, IWH, IWD, IWA, LBH, LBD, LBA, PSH, PSD, PSA, WHH, WHD, WHA, SJH, SJD, SJA, VCH, VCD, VCA, GBH, GBD, GBA, BSH, BSD, BSA FROM "Match";
DROP VIEW IF EXISTS "Soccer_Player_Stats";
CREATE VIEW Soccer_Player_Stats AS SELECT id AS attribute_record_id, player_fifa_api_id, player_api_id, date AS record_date, overall_rating, potential, preferred_foot, attacking_work_rate, defensive_work_rate, crossing, finishing, heading_accuracy, short_passing, volleys, dribbling, curve, free_kick_accuracy, long_passing, ball_control, acceleration, sprint_speed, agility, reactions, balance, shot_power, jumping, stamina, strength, long_shots, aggression, interceptions, positioning, vision, penalties, marking, standing_tackle, sliding_tackle, gk_diving, gk_handling, gk_kicking, gk_positioning, gk_reflexes FROM Player_Attributes;
DROP VIEW IF EXISTS "Soccer_Players";
CREATE VIEW Soccer_Players AS SELECT id AS internal_id, player_api_id, player_name, player_fifa_api_id, birthday AS birth_date, height AS height_cm, weight AS weight_lbs FROM Player;
DROP VIEW IF EXISTS "Soccer_Team_Stats";
CREATE VIEW Soccer_Team_Stats AS SELECT id AS team_attr_id, team_fifa_api_id, team_api_id, date AS record_date, buildUpPlaySpeed AS buildup_speed, buildUpPlaySpeedClass AS buildup_speed_class, buildUpPlayDribbling AS buildup_dribbling, buildUpPlayDribblingClass AS buildup_dribbling_class, buildUpPlayPassing AS buildup_passing, buildUpPlayPassingClass AS buildup_passing_class, buildUpPlayPositioningClass AS buildup_positioning_class, chanceCreationPassing AS chance_passing, chanceCreationPassingClass AS chance_passing_class, chanceCreationCrossing AS chance_crossing, chanceCreationCrossingClass AS chance_crossing_class, chanceCreationShooting AS chance_shooting, chanceCreationShootingClass AS chance_shooting_class, chanceCreationPositioningClass AS chance_positioning_class, defencePressure AS defense_pressure, defencePressureClass AS defense_pressure_class, defenceAggression AS defense_aggression, defenceAggressionClass AS defense_aggression_class, defenceTeamWidth AS defense_width, defenceTeamWidthClass AS defense_width_class, defenceDefenderLineClass AS defense_line_class FROM Team_Attributes;
DROP VIEW IF EXISTS "Soccer_Teams";
CREATE VIEW Soccer_Teams AS SELECT id AS internal_id, team_api_id, team_fifa_api_id, team_long_name, team_short_name FROM Team;

-- ==== org_views (64) ===========================================
DROP VIEW IF EXISTS "cluster10_atom_join_bond_join_molecule";
CREATE VIEW "cluster10_atom_join_bond_join_molecule" AS 
SELECT t1.atom_id, t1.element, t1.molecule_id AS atom_molecule_id, t2.bond_id, t2.bond_type, t2.molecule_id AS bond_molecule_id, t3.molecule_id AS molecule_molecule_id, t3.label FROM atom t1 INNER JOIN bond t2 ON t1.molecule_id = t2.molecule_id INNER JOIN molecule t3 ON t1.molecule_id = t3.molecule_id;
DROP VIEW IF EXISTS "cluster11_cards_join_legalities";
CREATE VIEW "cluster11_cards_join_legalities" AS 
SELECT t1.artist, t1.asciiName, t1.availability, t1.borderColor, t1.cardKingdomFoilId, t1.cardKingdomId, t1.colorIdentity, t1.colorIndicator, t1.colors, t1.convertedManaCost, t1.duelDeck, t1.edhrecRank, t1.faceConvertedManaCost, t1.faceName, t1.flavorName, t1.flavorText, t1.frameEffects, t1.frameVersion, t1.hand, t1.hasAlternativeDeckLimit, t1.hasContentWarning, t1.hasFoil, t1.hasNonFoil, t1.isAlternative, t1.isFullArt, t1.isOnlineOnly, t1.isOversized, t1.isPromo, t1.isReprint, t1.isReserved, t1.isStarter, t1.isStorySpotlight, t1.isTextless, t1.isTimeshifted, t1.keywords, t1.layout, t1.leadershipSkills, t1.life, t1.loyalty, t1.manaCost, t1.mcmId, t1.mcmMetaId, t1.mtgArenaId, t1.mtgjsonV4Id, t1.mtgoFoilId, t1.mtgoId, t1.multiverseId, t1.name, t1.number, t1.originalReleaseDate, t1.originalText, t1.originalType, t1.otherFaceIds, t1.power, t1.printings, t1.promoTypes, t1.purchaseUrls, t1.rarity, t1.scryfallId, t1.scryfallIllustrationId, t1.scryfallOracleId, t1.setCode, t1.side, t1.subtypes, t1.supertypes, t1.tcgplayerProductId, t1.text, t1.toughness, t1.type, t1.types, t1.variations, t1.watermark, t1.id AS cards_id, t1.uuid AS cards_uuid, t2.id AS legalities_id, t2.format, t2.status, t2.uuid AS legalities_uuid FROM cards t1 INNER JOIN legalities t2 ON t1.uuid = t2.uuid;
DROP VIEW IF EXISTS "cluster12_cards_join_rulings";
CREATE VIEW "cluster12_cards_join_rulings" AS 
SELECT t1.artist, t1.asciiName, t1.availability, t1.borderColor, t1.cardKingdomFoilId, t1.cardKingdomId, t1.colorIdentity, t1.colorIndicator, t1.colors, t1.convertedManaCost, t1.duelDeck, t1.edhrecRank, t1.faceConvertedManaCost, t1.faceName, t1.flavorName, t1.flavorText, t1.frameEffects, t1.frameVersion, t1.hand, t1.hasAlternativeDeckLimit, t1.hasContentWarning, t1.hasFoil, t1.hasNonFoil, t1.isAlternative, t1.isFullArt, t1.isOnlineOnly, t1.isOversized, t1.isPromo, t1.isReprint, t1.isReserved, t1.isStarter, t1.isStorySpotlight, t1.isTextless, t1.isTimeshifted, t1.keywords, t1.layout, t1.leadershipSkills, t1.life, t1.loyalty, t1.manaCost, t1.mcmId, t1.mcmMetaId, t1.mtgArenaId, t1.mtgjsonV4Id, t1.mtgoFoilId, t1.mtgoId, t1.multiverseId, t1.name, t1.number, t1.originalReleaseDate, t1.originalText, t1.originalType, t1.otherFaceIds, t1.power, t1.printings, t1.promoTypes, t1.purchaseUrls, t1.rarity, t1.scryfallId, t1.scryfallIllustrationId, t1.scryfallOracleId, t1.setCode, t1.side, t1.subtypes, t1.supertypes, t1.tcgplayerProductId, t1.text, t1.toughness, t1.type, t1.types, t1.variations, t1.watermark, t1.id AS cards_id, t1.uuid AS cards_uuid, t2.id AS rulings_id, t2.date, t2.text AS rulings_text, t2.uuid AS rulings_uuid FROM cards t1 INNER JOIN rulings t2 ON t1.uuid = t2.uuid;
DROP VIEW IF EXISTS "cluster13_cards_join_set_translations";
CREATE VIEW "cluster13_cards_join_set_translations" AS 
SELECT t1.artist, t1.asciiName, t1.availability, t1.borderColor, t1.cardKingdomFoilId, t1.cardKingdomId, t1.colorIdentity, t1.colorIndicator, t1.colors, t1.convertedManaCost, t1.duelDeck, t1.edhrecRank, t1.faceConvertedManaCost, t1.faceName, t1.flavorName, t1.flavorText, t1.frameEffects, t1.frameVersion, t1.hand, t1.hasAlternativeDeckLimit, t1.hasContentWarning, t1.hasFoil, t1.hasNonFoil, t1.isAlternative, t1.isFullArt, t1.isOnlineOnly, t1.isOversized, t1.isPromo, t1.isReprint, t1.isReserved, t1.isStarter, t1.isStorySpotlight, t1.isTextless, t1.isTimeshifted, t1.keywords, t1.layout, t1.leadershipSkills, t1.life, t1.loyalty, t1.manaCost, t1.mcmId, t1.mcmMetaId, t1.mtgArenaId, t1.mtgjsonV4Id, t1.mtgoFoilId, t1.mtgoId, t1.multiverseId, t1.name, t1.number, t1.originalReleaseDate, t1.originalText, t1.originalType, t1.otherFaceIds, t1.power, t1.printings, t1.promoTypes, t1.purchaseUrls, t1.rarity, t1.scryfallId, t1.scryfallIllustrationId, t1.scryfallOracleId, t1.side, t1.subtypes, t1.supertypes, t1.tcgplayerProductId, t1.text, t1.toughness, t1.type, t1.types, t1.uuid, t1.variations, t1.watermark, t1.id AS cards_id, t1.setCode AS cards_setCode, t2.id AS set_translations_id, t2.language, t2.translation, t2.setCode AS set_translations_setCode FROM cards t1 INNER JOIN set_translations t2 ON t1.setCode = t2.setCode;
DROP VIEW IF EXISTS "cluster14_cards_join_foreign_data";
CREATE VIEW "cluster14_cards_join_foreign_data" AS 
SELECT t1.artist, t1.asciiName, t1.availability, t1.borderColor, t1.cardKingdomFoilId, t1.cardKingdomId, t1.colorIdentity, t1.colorIndicator, t1.colors, t1.convertedManaCost, t1.duelDeck, t1.edhrecRank, t1.faceConvertedManaCost, t1.faceName, t1.flavorName, t1.flavorText, t1.frameEffects, t1.frameVersion, t1.hand, t1.hasAlternativeDeckLimit, t1.hasContentWarning, t1.hasFoil, t1.hasNonFoil, t1.isAlternative, t1.isFullArt, t1.isOnlineOnly, t1.isOversized, t1.isPromo, t1.isReprint, t1.isReserved, t1.isStarter, t1.isStorySpotlight, t1.isTextless, t1.isTimeshifted, t1.keywords, t1.layout, t1.leadershipSkills, t1.life, t1.loyalty, t1.manaCost, t1.mcmId, t1.mcmMetaId, t1.mtgArenaId, t1.mtgjsonV4Id, t1.mtgoFoilId, t1.mtgoId, t1.multiverseId, t1.name AS cards_name, t1.number, t1.originalReleaseDate, t1.originalText, t1.originalType, t1.otherFaceIds, t1.power, t1.printings, t1.promoTypes, t1.purchaseUrls, t1.rarity, t1.scryfallId, t1.scryfallIllustrationId, t1.scryfallOracleId, t1.setCode, t1.side, t1.subtypes, t1.supertypes, t1.tcgplayerProductId, t1.text AS cards_text, t1.toughness, t1.type AS cards_type, t1.types, t1.variations, t1.watermark, t1.id AS cards_id, t1.uuid AS cards_uuid, t2.id AS foreign_data_id, t2.flavorText AS foreign_data_flavorText, t2.language, t2.multiverseid, t2.name AS foreign_data_name, t2.text AS foreign_data_text, t2.type AS foreign_data_type, t2.uuid AS foreign_data_uuid FROM cards t1 INNER JOIN foreign_data t2 ON t1.uuid = t2.uuid;
DROP VIEW IF EXISTS "cluster15_set_translations_join_sets";
CREATE VIEW "cluster15_set_translations_join_sets" AS 
SELECT t1.language, t1.translation, t1.id AS set_translations_id, t1.setCode AS set_translations_setCode, t2.id AS sets_id, t2.baseSetSize, t2.block, t2.booster, t2.code AS sets_code, t2.isFoilOnly, t2.isForeignOnly, t2.isNonFoilOnly, t2.isOnlineOnly, t2.isPartialPreview, t2.keyruneCode, t2.mcmId, t2.mcmIdExtras, t2.mcmName, t2.mtgoCode, t2.name, t2.parentCode, t2.releaseDate, t2.tcgplayerGroupId, t2.totalSetSize, t2.type FROM set_translations t1 INNER JOIN sets t2 ON t1.setCode = t2.code;
DROP VIEW IF EXISTS "cluster16_cards_join_sets";
CREATE VIEW "cluster16_cards_join_sets" AS 
SELECT t1.artist, t1.asciiName, t1.availability, t1.borderColor, t1.cardKingdomFoilId, t1.cardKingdomId, t1.colorIdentity, t1.colorIndicator, t1.colors, t1.convertedManaCost, t1.duelDeck, t1.edhrecRank, t1.faceConvertedManaCost, t1.faceName, t1.flavorName, t1.flavorText, t1.frameEffects, t1.frameVersion, t1.hand, t1.hasAlternativeDeckLimit, t1.hasContentWarning, t1.hasFoil, t1.hasNonFoil, t1.isAlternative, t1.isFullArt, t1.isOnlineOnly, t1.isOversized, t1.isPromo, t1.isReprint, t1.isReserved, t1.isStarter, t1.isStorySpotlight, t1.isTextless, t1.isTimeshifted, t1.keywords, t1.layout, t1.leadershipSkills, t1.life, t1.loyalty, t1.manaCost, t1.mcmId AS cards_mcmId, t1.mcmMetaId, t1.mtgArenaId, t1.mtgjsonV4Id, t1.mtgoFoilId, t1.mtgoId, t1.multiverseId, t1.name AS cards_name, t1.number, t1.originalReleaseDate, t1.originalText, t1.originalType, t1.otherFaceIds, t1.power, t1.printings, t1.promoTypes, t1.purchaseUrls, t1.rarity, t1.scryfallId, t1.scryfallIllustrationId, t1.scryfallOracleId, t1.side, t1.subtypes, t1.supertypes, t1.tcgplayerProductId, t1.text, t1.toughness, t1.type AS cards_type, t1.types, t1.uuid, t1.variations, t1.watermark, t1.id AS cards_id, t1.setCode AS cards_setCode, t2.id AS sets_id, t2.baseSetSize, t2.block, t2.booster, t2.code AS sets_code, t2.isFoilOnly, t2.isForeignOnly, t2.isNonFoilOnly, t2.isOnlineOnly, t2.isPartialPreview, t2.keyruneCode, t2.mcmId AS sets_mcmId, t2.mcmIdExtras, t2.mcmName, t2.mtgoCode, t2.name AS sets_name, t2.parentCode, t2.releaseDate, t2.tcgplayerGroupId, t2.totalSetSize, t2.type AS sets_type FROM cards t1 INNER JOIN sets t2 ON t1.setCode = t2.code;
DROP VIEW IF EXISTS "cluster17_posts_join_users";
CREATE VIEW "cluster17_posts_join_users" AS 
SELECT t1.PostTypeId, t1.AcceptedAnswerId, t1.CreaionDate AS posts_CreaionDate, t1.Score, t1.ViewCount, t1.Body, t1.LasActivityDate, t1.Title, t1.Tags, t1.AnswerCount, t1.CommentCount, t1.FavoriteCount, t1.LastEditorUserId, t1.LastEditDate, t1.CommunityOwnedDate, t1.ParentId, t1.ClosedDate, t1.OwnerDisplayName, t1.LastEditorDisplayName, t1.Id AS posts_Id, t1.OwnerUserId, t2.Id AS users_Id, t2.Reputation, t2.CreationDate AS users_CreationDate, t2.DisplayName, t2.LastAccessDate, t2.WebsiteUrl, t2.Location, t2.AboutMe, t2.Views, t2.UpVotes, t2.DownVotes, t2.AccountId, t2.Age, t2.ProfileImageUrl FROM posts t1 INNER JOIN users t2 ON t1.OwnerUserId = t2.Id;
DROP VIEW IF EXISTS "cluster18_badges_join_users";
CREATE VIEW "cluster18_badges_join_users" AS 
SELECT t1.Name, t1.Date, t1.Id AS badges_Id, t1.UserId AS badges_UserId, t2.Id AS users_Id, t2.Reputation, t2.CreationDate, t2.DisplayName, t2.LastAccessDate, t2.WebsiteUrl, t2.Location, t2.AboutMe, t2.Views, t2.UpVotes, t2.DownVotes, t2.AccountId, t2.Age, t2.ProfileImageUrl FROM badges t1 INNER JOIN users t2 ON t1.UserId = t2.Id;
DROP VIEW IF EXISTS "cluster19_comments_join_posts";
CREATE VIEW "cluster19_comments_join_posts" AS 
SELECT t1.Score AS comments_Score, t1.Text, t1.CreationDate AS comments_CreationDate, t1.UserId, t1.UserDisplayName, t1.Id AS comments_Id, t1.PostId, t2.Id AS posts_Id, t2.PostTypeId, t2.AcceptedAnswerId, t2.CreaionDate AS posts_CreaionDate, t2.Score AS posts_Score, t2.ViewCount, t2.Body, t2.OwnerUserId, t2.LasActivityDate, t2.Title, t2.Tags, t2.AnswerCount, t2.CommentCount, t2.FavoriteCount, t2.LastEditorUserId, t2.LastEditDate, t2.CommunityOwnedDate, t2.ParentId, t2.ClosedDate, t2.OwnerDisplayName, t2.LastEditorDisplayName FROM comments t1 INNER JOIN posts t2 ON t1.PostId = t2.Id;
DROP VIEW IF EXISTS "cluster1_frpm_join_schools";
CREATE VIEW "cluster1_frpm_join_schools" AS 
SELECT t1."Academic Year", t1."County Code", t1."District Code", t1."School Code", t1."County Name", t1."District Name", t1."School Name", t1."District Type", t1."School Type", t1."Educational Option Type", t1."NSLP Provision Status", t1."Charter School (Y/N)", t1."Charter School Number", t1."Charter Funding Type", t1.IRC, t1."Low Grade", t1."High Grade", t1."Enrollment (K-12)", t1."Free Meal Count (K-12)", t1."Percent (%) Eligible Free (K-12)", t1."FRPM Count (K-12)", t1."Percent (%) Eligible FRPM (K-12)", t1."Enrollment (Ages 5-17)", t1."Free Meal Count (Ages 5-17)", t1."Percent (%) Eligible Free (Ages 5-17)", t1."FRPM Count (Ages 5-17)", t1."Percent (%) Eligible FRPM (Ages 5-17)", t1."2013-14 CALPADS Fall 1 Certification Status", t1.CDSCode AS frpm_CDSCode, t2.CDSCode AS schools_CDSCode, t2.NCESDist, t2.NCESSchool, t2.StatusType, t2.County, t2.District, t2.School, t2.Street, t2.StreetAbr, t2.City, t2.Zip, t2.State, t2.MailStreet, t2.MailStrAbr, t2.MailCity, t2.MailZip, t2.MailState, t2.Phone, t2.Ext, t2.Website, t2.OpenDate, t2.ClosedDate, t2.Charter, t2.CharterNum, t2.FundingType, t2.DOC, t2.DOCType, t2.SOC, t2.SOCType, t2.EdOpsCode, t2.EdOpsName, t2.EILCode, t2.EILName, t2.GSoffered, t2.GSserved, t2.Virtual, t2.Magnet, t2.Latitude, t2.Longitude, t2.AdmFName1, t2.AdmLName1, t2.AdmEmail1, t2.AdmFName2, t2.AdmLName2, t2.AdmEmail2, t2.AdmFName3, t2.AdmLName3, t2.AdmEmail3, t2.LastUpdate FROM frpm t1 INNER JOIN schools t2 ON t1.CDSCode = t2.CDSCode;
DROP VIEW IF EXISTS "cluster20_posthistory_join_posts_join_users";
CREATE VIEW "cluster20_posthistory_join_posts_join_users" AS 
SELECT t1.PostHistoryTypeId, t1.RevisionGUID, t1.CreationDate AS postHistory_CreationDate, t1.Text, t1.Comment, t1.UserDisplayName AS postHistory_UserDisplayName, t1.Id AS postHistory_Id, t1.PostId AS postHistory_PostId, t1.UserId AS postHistory_UserId, t2.Id AS posts_Id, t2.PostTypeId, t2.AcceptedAnswerId, t2.CreaionDate, t2.Score, t2.ViewCount, t2.Body, t2.OwnerUserId, t2.LasActivityDate, t2.Title, t2.Tags, t2.AnswerCount, t2.CommentCount, t2.FavoriteCount, t2.LastEditorUserId, t2.LastEditDate, t2.CommunityOwnedDate, t2.ParentId, t2.ClosedDate, t2.OwnerDisplayName, t2.LastEditorDisplayName, t3.Id AS users_Id, t3.Reputation, t3.CreationDate AS users_CreationDate, t3.DisplayName, t3.LastAccessDate, t3.WebsiteUrl, t3.Location, t3.AboutMe, t3.Views, t3.UpVotes, t3.DownVotes, t3.AccountId, t3.Age, t3.ProfileImageUrl FROM postHistory t1 INNER JOIN posts t2 ON t1.PostId = t2.Id INNER JOIN users t3 ON t1.UserId = t3.Id;
DROP VIEW IF EXISTS "cluster21_hero_power_join_superhero_join_superpower";
CREATE VIEW "cluster21_hero_power_join_superhero_join_superpower" AS 
SELECT t1.hero_id AS hero_power_hero_id, t1.power_id AS hero_power_power_id, t2.id AS superhero_id, t2.superhero_name, t2.full_name, t2.gender_id, t2.eye_colour_id, t2.hair_colour_id, t2.skin_colour_id, t2.race_id, t2.publisher_id, t2.alignment_id, t2.height_cm, t2.weight_kg, t3.id AS superpower_id, t3.power_name FROM hero_power t1 INNER JOIN superhero t2 ON t1.hero_id = t2.id INNER JOIN superpower t3 ON t1.power_id = t3.id;
DROP VIEW IF EXISTS "cluster22_publisher_join_superhero";
CREATE VIEW "cluster22_publisher_join_superhero" AS 
SELECT t1.publisher_name, t1.id AS publisher_id, t2.id AS superhero_id, t2.superhero_name, t2.full_name, t2.gender_id, t2.eye_colour_id, t2.hair_colour_id, t2.skin_colour_id, t2.race_id, t2.publisher_id AS superhero_publisher_id, t2.alignment_id, t2.height_cm, t2.weight_kg FROM publisher t1 INNER JOIN superhero t2 ON t1.id = t2.publisher_id;
DROP VIEW IF EXISTS "cluster23_colour_join_superhero";
CREATE VIEW "cluster23_colour_join_superhero" AS 
SELECT t1.colour, t1.id AS colour_id, t2.id AS superhero_id, t2.superhero_name, t2.full_name, t2.gender_id, t2.eye_colour_id, t2.hair_colour_id, t2.skin_colour_id, t2.race_id, t2.publisher_id, t2.alignment_id, t2.height_cm, t2.weight_kg FROM colour t1 INNER JOIN superhero t2 ON t1.id = t2.eye_colour_id;
DROP VIEW IF EXISTS "cluster24_race_join_superhero";
CREATE VIEW "cluster24_race_join_superhero" AS 
SELECT t1.race, t1.id AS race_id, t2.id AS superhero_id, t2.superhero_name, t2.full_name, t2.gender_id, t2.eye_colour_id, t2.hair_colour_id, t2.skin_colour_id, t2.race_id AS superhero_race_id, t2.publisher_id, t2.alignment_id, t2.height_cm, t2.weight_kg FROM race t1 INNER JOIN superhero t2 ON t1.id = t2.race_id;
DROP VIEW IF EXISTS "cluster25_circuits_join_races";
CREATE VIEW "cluster25_circuits_join_races" AS 
SELECT t1.circuitRef, t1.name AS circuits_name, t1.location, t1.country, t1.lat, t1.lng, t1.alt, t1.url AS circuits_url, t1.circuitId AS circuits_circuitId, t2.raceId, t2.year, t2.round, t2.circuitId AS races_circuitId, t2.name AS races_name, t2.date, t2.time, t2.url AS races_url FROM circuits t1 INNER JOIN races t2 ON t1.circuitId = t2.circuitId;
DROP VIEW IF EXISTS "cluster26_drivers_join_qualifying";
CREATE VIEW "cluster26_drivers_join_qualifying" AS 
SELECT t1.driverRef, t1.number AS drivers_number, t1.code, t1.forename, t1.surname, t1.dob, t1.nationality, t1.url, t1.driverId AS drivers_driverId, t2.qualifyId, t2.raceId, t2.driverId AS qualifying_driverId, t2.constructorId, t2.number AS qualifying_number, t2.position, t2.q1, t2.q2, t2.q3 FROM drivers t1 INNER JOIN qualifying t2 ON t1.driverId = t2.driverId;
DROP VIEW IF EXISTS "cluster27_races_join_results";
CREATE VIEW "cluster27_races_join_results" AS 
SELECT t1.year, t1.round, t1.circuitId, t1.name AS races_name, t1.date, t1.time AS races_time, t1.url AS races_url, t1.raceId AS races_raceId, t2.resultId, t2.raceId AS results_raceId, t2.driverId, t2.constructorId, t2.number, t2.grid, t2.position, t2.positionText, t2.positionOrder, t2.points, t2.laps, t2.time AS results_time, t2.milliseconds, t2.fastestLap, t2.rank, t2.fastestLapTime, t2.fastestLapSpeed, t2.statusId FROM races t1 INNER JOIN results t2 ON t1.raceId = t2.raceId;
DROP VIEW IF EXISTS "cluster28_drivers_join_results";
CREATE VIEW "cluster28_drivers_join_results" AS 
SELECT t1.driverRef, t1.number AS drivers_number, t1.code, t1.forename, t1.surname, t1.dob, t1.nationality, t1.url, t1.driverId AS drivers_driverId, t2.resultId, t2.raceId, t2.driverId AS results_driverId, t2.constructorId, t2.number AS results_number, t2.grid, t2.position, t2.positionText, t2.positionOrder, t2.points, t2.laps, t2.time, t2.milliseconds, t2.fastestLap, t2.rank, t2.fastestLapTime, t2.fastestLapSpeed, t2.statusId FROM drivers t1 INNER JOIN results t2 ON t1.driverId = t2.driverId;
DROP VIEW IF EXISTS "cluster29_driverstandings_join_drivers_join_races";
CREATE VIEW "cluster29_driverstandings_join_drivers_join_races" AS 
SELECT t1.points AS driverStandings_points, t1.position AS driverStandings_position, t1.positionText, t1.wins, t1.driverStandingsId, t1.raceId AS driverStandings_raceId, t1.driverId AS driverStandings_driverId, t2.driverId AS drivers_driverId, t2.driverRef, t2.number, t2.code, t2.forename, t2.surname, t2.dob, t2.nationality, t2.url AS drivers_url, t3.raceId AS races_raceId, t3.year, t3.round, t3.circuitId, t3.name, t3.date, t3.time, t3.url AS races_url FROM driverStandings t1 INNER JOIN drivers t2 ON t1.driverId = t2.driverId INNER JOIN races t3 ON t1.raceId = t3.raceId;
DROP VIEW IF EXISTS "cluster2_satscores_join_schools";
CREATE VIEW "cluster2_satscores_join_schools" AS 
SELECT 
  t1.cds AS satscores_cds, t1.rtype, t1.sname, t1.dname, t1.cname, t1.enroll12, t1.NumTstTakr, t1.AvgScrRead, t1.AvgScrMath, t1.AvgScrWrite, t1.NumGE1500,
  t2.CDSCode AS schools_CDSCode, t2.NCESDist, t2.NCESSchool, t2.StatusType, t2.County, t2.District, t2.School, t2.Street, t2.StreetAbr, t2.City, t2.Zip, t2.State, t2.MailStreet, t2.MailStrAbr, t2.MailCity, t2.MailZip, t2.MailState, t2.Phone, t2.Ext, t2.Website, t2.OpenDate, t2.ClosedDate, t2.Charter, t2.CharterNum, t2.FundingType, t2.DOC, t2.DOCType, t2.SOC, t2.SOCType, t2.EdOpsCode, t2.EdOpsName, t2.EILCode, t2.EILName, t2.GSoffered, t2.GSserved, t2.Virtual, t2.Magnet, t2.Latitude, t2.Longitude, t2.AdmFName1, t2.AdmLName1, t2.AdmEmail1, t2.AdmFName2, t2.AdmLName2, t2.AdmEmail2, t2.AdmFName3, t2.AdmLName3, t2.AdmEmail3, t2.LastUpdate 
FROM satscores t1 INNER JOIN schools t2 ON t1.cds = t2.CDSCode;
DROP VIEW IF EXISTS "cluster30_drivers_join_races_join_results";
CREATE VIEW "cluster30_drivers_join_races_join_results" AS 
SELECT t1.driverRef, t1.number AS drivers_number, t1.code, t1.forename, t1.surname, t1.dob, t1.nationality, t1.url AS drivers_url, t1.driverId AS drivers_driverId, t2.raceId AS races_raceId, t2.year, t2.round, t2.circuitId, t2.name, t2.date, t2.time AS races_time, t2.url AS races_url, t3.resultId, t3.raceId AS results_raceId, t3.driverId AS results_driverId, t3.constructorId, t3.number AS results_number, t3.grid, t3.position, t3.positionText, t3.positionOrder, t3.points, t3.laps, t3.time AS results_time, t3.milliseconds, t3.fastestLap, t3.rank, t3.fastestLapTime, t3.fastestLapSpeed, t3.statusId FROM drivers t1 INNER JOIN results t3 ON t1.driverId = t3.driverId INNER JOIN races t2 ON t3.raceId = t2.raceId;
DROP VIEW IF EXISTS "cluster31_league_join_match";
CREATE VIEW "cluster31_league_join_match" AS
SELECT 
    t1.id AS League_id, t1.country_id AS League_country_id, t1.name AS League_name,
    t2.id AS Match_id, t2.country_id AS Match_country_id, t2.league_id AS Match_league_id, 
    t2.season, t2.stage, t2.date, t2.match_api_id, t2.home_team_api_id, t2.away_team_api_id, t2.home_team_goal, t2.away_team_goal, 
    t2.home_player_X1, t2.home_player_X2, t2.home_player_X3, t2.home_player_X4, t2.home_player_X5, t2.home_player_X6, t2.home_player_X7, t2.home_player_X8, t2.home_player_X9, t2.home_player_X10, t2.home_player_X11, 
    t2.away_player_X1, t2.away_player_X2, t2.away_player_X3, t2.away_player_X4, t2.away_player_X5, t2.away_player_X6, t2.away_player_X7, t2.away_player_X8, t2.away_player_X9, t2.away_player_X10, t2.away_player_X11, 
    t2.home_player_Y1, t2.home_player_Y2, t2.home_player_Y3, t2.home_player_Y4, t2.home_player_Y5, t2.home_player_Y6, t2.home_player_Y7, t2.home_player_Y8, t2.home_player_Y9, t2.home_player_Y10, t2.home_player_Y11, 
    t2.away_player_Y1, t2.away_player_Y2, t2.away_player_Y3, t2.away_player_Y4, t2.away_player_Y5, t2.away_player_Y6, t2.away_player_Y7, t2.away_player_Y8, t2.away_player_Y9, t2.away_player_Y10, t2.away_player_Y11, 
    t2.home_player_1, t2.home_player_2, t2.home_player_3, t2.home_player_4, t2.home_player_5, t2.home_player_6, t2.home_player_7, t2.home_player_8, t2.home_player_9, t2.home_player_10, t2.home_player_11, 
    t2.away_player_1, t2.away_player_2, t2.away_player_3, t2.away_player_4, t2.away_player_5, t2.away_player_6, t2.away_player_7, t2.away_player_8, t2.away_player_9, t2.away_player_10, t2.away_player_11, 
    t2.goal, t2.shoton, t2.shotoff, t2.foulcommit, t2.card, t2."cross", t2.corner, t2.possession, 
    t2.B365H, t2.B365D, t2.B365A, t2.BWH, t2.BWD, t2.BWA, t2.IWH, t2.IWD, t2.IWA, t2.LBH, t2.LBD, t2.LBA, t2.PSH, t2.PSD, t2.PSA, t2.WHH, t2.WHD, t2.WHA, t2.SJH, t2.SJD, t2.SJA, t2.VCH, t2.VCD, t2.VCA, t2.GBH, t2.GBD, t2.GBA, t2.BSH, t2.BSD, t2.BSA
FROM League t1 INNER JOIN "Match" t2 ON t1.id = t2.league_id;
DROP VIEW IF EXISTS "cluster32_player_join_player_attributes";
CREATE VIEW "cluster32_player_join_player_attributes" AS 
SELECT t1.player_name, t1.birthday, t1.height, t1.weight, t1.id AS Player_id, t1.player_api_id AS Player_player_api_id, t1.player_fifa_api_id AS Player_player_fifa_api_id, t2.id AS Player_Attributes_id, t2.player_fifa_api_id AS Player_Attributes_player_fifa_api_id, t2.player_api_id AS Player_Attributes_player_api_id, t2.date, t2.overall_rating, t2.potential, t2.preferred_foot, t2.attacking_work_rate, t2.defensive_work_rate, t2.crossing, t2.finishing, t2.heading_accuracy, t2.short_passing, t2.volleys, t2.dribbling, t2.curve, t2.free_kick_accuracy, t2.long_passing, t2.ball_control, t2.acceleration, t2.sprint_speed, t2.agility, t2.reactions, t2.balance, t2.shot_power, t2.jumping, t2.stamina, t2.strength, t2.long_shots, t2.aggression, t2.interceptions, t2.positioning, t2.vision, t2.penalties, t2.marking, t2.standing_tackle, t2.sliding_tackle, t2.gk_diving, t2.gk_handling, t2.gk_kicking, t2.gk_positioning, t2.gk_reflexes FROM Player t1 INNER JOIN Player_Attributes t2 ON t1.player_api_id = t2.player_api_id;
DROP VIEW IF EXISTS "cluster33_team_join_team_attributes";
CREATE VIEW "cluster33_team_join_team_attributes" AS 
SELECT t1.team_long_name, t1.team_short_name, t1.id AS Team_id, t1.team_api_id AS Team_team_api_id, t1.team_fifa_api_id AS Team_team_fifa_api_id, t2.id AS Team_Attributes_id, t2.team_fifa_api_id AS Team_Attributes_team_fifa_api_id, t2.team_api_id AS Team_Attributes_team_api_id, t2.date, t2.buildUpPlaySpeed, t2.buildUpPlaySpeedClass, t2.buildUpPlayDribbling, t2.buildUpPlayDribblingClass, t2.buildUpPlayPassing, t2.buildUpPlayPassingClass, t2.buildUpPlayPositioningClass, t2.chanceCreationPassing, t2.chanceCreationPassingClass, t2.chanceCreationCrossing, t2.chanceCreationCrossingClass, t2.chanceCreationShooting, t2.chanceCreationShootingClass, t2.chanceCreationPositioningClass, t2.defencePressure, t2.defencePressureClass, t2.defenceAggression, t2.defenceAggressionClass, t2.defenceTeamWidth, t2.defenceTeamWidthClass, t2.defenceDefenderLineClass FROM Team t1 INNER JOIN Team_Attributes t2 ON t1.team_api_id = t2.team_api_id;
DROP VIEW IF EXISTS "cluster34_laboratory_join_patient";
CREATE VIEW "cluster34_laboratory_join_patient" AS 
SELECT t1.Date, t1.GOT, t1.GPT, t1.LDH, t1.ALP, t1.TP, t1.ALB, t1.UA, t1.UN, t1.CRE, t1."T-BIL", t1."T-CHO", t1.TG, t1.CPK, t1.GLU, t1.WBC, t1.RBC, t1.HGB, t1.HCT, t1.PLT, t1.PT, t1.APTT, t1.FG, t1.PIC, t1.TAT, t1.TAT2, t1."U-PRO", t1.IGG, t1.IGA, t1.IGM, t1.CRP, t1.RA, t1.RF, t1.C3, t1.C4, t1.RNP, t1.SM, t1.SC170, t1.SSA, t1.SSB, t1.CENTROMEA, t1.DNA, t1."DNA-II", t1.ID AS Laboratory_ID, t2.ID AS Patient_ID, t2.SEX, t2.Birthday, t2.Description, t2."First Date", t2.Admission, t2.Diagnosis FROM Laboratory t1 INNER JOIN Patient t2 ON t1.ID = t2.ID;
DROP VIEW IF EXISTS "cluster35_examination_join_patient";
CREATE VIEW "cluster35_examination_join_patient" AS 
SELECT t1."Examination Date", t1."aCL IgG", t1."aCL IgM", t1.ANA, t1."ANA Pattern", t1."aCL IgA", t1.Diagnosis AS Examination_Diagnosis, t1.KCT, t1.RVVT, t1.LAC, t1.Symptoms, t1.Thrombosis, t1.ID AS Examination_ID, t2.ID AS Patient_ID, t2.SEX, t2.Birthday, t2.Description, t2."First Date", t2.Admission, t2.Diagnosis AS Patient_Diagnosis FROM Examination t1 INNER JOIN Patient t2 ON t1.ID = t2.ID;
DROP VIEW IF EXISTS "cluster36_examination_join_laboratory_join_patient";
CREATE VIEW "cluster36_examination_join_laboratory_join_patient" AS 
SELECT t1."Examination Date", t1."aCL IgG", t1."aCL IgM", t1.ANA, t1."ANA Pattern", t1."aCL IgA", t1.Diagnosis AS Examination_Diagnosis, t1.KCT, t1.RVVT, t1.LAC, t1.Symptoms, t1.Thrombosis, t1.ID AS Examination_ID, t2.ID AS Laboratory_ID, t2.Date, t2.GOT, t2.GPT, t2.LDH, t2.ALP, t2.TP, t2.ALB, t2.UA, t2.UN, t2.CRE, t2."T-BIL", t2."T-CHO", t2.TG, t2.CPK, t2.GLU, t2.WBC, t2.RBC, t2.HGB, t2.HCT, t2.PLT, t2.PT, t2.APTT, t2.FG, t2.PIC, t2.TAT, t2.TAT2, t2."U-PRO", t2.IGG, t2.IGA, t2.IGM, t2.CRP, t2.RA, t2.RF, t2.C3, t2.C4, t2.RNP, t2.SM, t2.SC170, t2.SSA, t2.SSB, t2.CENTROMEA, t2.DNA, t2."DNA-II", t3.ID AS Patient_ID, t3.SEX, t3.Birthday, t3.Description, t3."First Date", t3.Admission, t3.Diagnosis AS Patient_Diagnosis FROM Examination t1 INNER JOIN Laboratory t2 ON t1.ID = t2.ID INNER JOIN Patient t3 ON t1.ID = t3.ID;
DROP VIEW IF EXISTS "cluster37_examination_join_laboratory";
CREATE VIEW "cluster37_examination_join_laboratory" AS 
SELECT t1."Examination Date", t1."aCL IgG", t1."aCL IgM", t1.ANA, t1."ANA Pattern", t1."aCL IgA", t1.Diagnosis, t1.KCT, t1.RVVT, t1.LAC, t1.Symptoms, t1.Thrombosis, t1.ID AS Examination_ID, t2.ID AS Laboratory_ID, t2.Date, t2.GOT, t2.GPT, t2.LDH, t2.ALP, t2.TP, t2.ALB, t2.UA, t2.UN, t2.CRE, t2."T-BIL", t2."T-CHO", t2.TG, t2.CPK, t2.GLU, t2.WBC, t2.RBC, t2.HGB, t2.HCT, t2.PLT, t2.PT, t2.APTT, t2.FG, t2.PIC, t2.TAT, t2.TAT2, t2."U-PRO", t2.IGG, t2.IGA, t2.IGM, t2.CRP, t2.RA, t2.RF, t2.C3, t2.C4, t2.RNP, t2.SM, t2.SC170, t2.SSA, t2.SSB, t2.CENTROMEA, t2.DNA, t2."DNA-II" FROM Examination t1 INNER JOIN Laboratory t2 ON t1.ID = t2.ID;
DROP VIEW IF EXISTS "cluster38_major_join_member";
CREATE VIEW "cluster38_major_join_member" AS 
SELECT t1.major_name, t1.department, t1.college, t1.major_id AS major_major_id, t2.member_id, t2.first_name, t2.last_name, t2.email, t2.position, t2.t_shirt_size, t2.phone, t2.zip, t2.link_to_major FROM major t1 INNER JOIN member t2 ON t1.major_id = t2.link_to_major;
DROP VIEW IF EXISTS "cluster39_budget_join_event";
CREATE VIEW "cluster39_budget_join_event" AS 
SELECT t1.budget_id, t1.category, t1.spent, t1.remaining, t1.amount, t1.event_status AS budget_event_status, t1.link_to_event, t2.event_id, t2.event_name, t2.event_date, t2.type, t2.notes, t2.location, t2.status AS event_status FROM budget t1 INNER JOIN event t2 ON t1.link_to_event = t2.event_id;
DROP VIEW IF EXISTS "cluster3_account_join_district";
CREATE VIEW "cluster3_account_join_district" AS 
SELECT t1.account_id, t1.frequency, t1.date, t1.district_id AS account_district_id, t2.district_id AS district_district_id, t2.A2, t2.A3, t2.A4, t2.A5, t2.A6, t2.A7, t2.A8, t2.A9, t2.A10, t2.A11, t2.A12, t2.A13, t2.A14, t2.A15, t2.A16 FROM account t1 INNER JOIN district t2 ON t1.district_id = t2.district_id;
DROP VIEW IF EXISTS "cluster40_member_join_zip_code";
CREATE VIEW "cluster40_member_join_zip_code" AS 
SELECT t1.member_id, t1.first_name, t1.last_name, t1.email, t1.position, t1.t_shirt_size, t1.phone, t1.link_to_major, t1.zip AS member_zip, t2.zip_code AS zip_code_zip_code, t2.type, t2.city, t2.county, t2.state, t2.short_state FROM member t1 INNER JOIN zip_code t2 ON t1.zip = t2.zip_code;
DROP VIEW IF EXISTS "cluster41_expense_join_member";
CREATE VIEW "cluster41_expense_join_member" AS 
SELECT t1.expense_id, t1.expense_description, t1.expense_date, t1.cost, t1.approved, t1.link_to_budget, t1.link_to_member AS expense_link_to_member, t2.member_id AS member_member_id, t2.first_name, t2.last_name, t2.email, t2.position, t2.t_shirt_size, t2.phone, t2.zip, t2.link_to_major FROM expense t1 INNER JOIN member t2 ON t1.link_to_member = t2.member_id;
DROP VIEW IF EXISTS "cluster42_customers_join_yearmonth";
CREATE VIEW "cluster42_customers_join_yearmonth" AS 
SELECT t1.Segment, t1.Currency, t1.CustomerID AS customers_CustomerID, t2.CustomerID AS yearmonth_CustomerID, t2.Date, t2.Consumption FROM customers t1 INNER JOIN yearmonth t2 ON t1.CustomerID = t2.CustomerID;
DROP VIEW IF EXISTS "cluster43_gasstations_join_transactions_1k";
CREATE VIEW "cluster43_gasstations_join_transactions_1k" AS 
SELECT t1.ChainID, t1.Country, t1.Segment, t1.GasStationID AS gasstations_GasStationID, t2.TransactionID, t2.Date, t2.Time, t2.CustomerID, t2.CardID, t2.ProductID, t2.Amount, t2.Price, t2.GasStationID AS transactions_1k_GasStationID FROM gasstations t1 INNER JOIN transactions_1k t2 ON t1.GasStationID = t2.GasStationID;
DROP VIEW IF EXISTS "cluster44_account_join_district_join_loan";
CREATE VIEW "cluster44_account_join_district_join_loan" AS 
SELECT t1.account_id AS account_account_id, t1.frequency, t1.date AS account_date, t1.district_id AS account_district_id, t2.district_id AS district_district_id, t2.A2, t2.A3, t2.A4, t2.A5, t2.A6, t2.A7, t2.A8, t2.A9, t2.A10, t2.A11, t2.A12, t2.A13, t2.A14, t2.A15, t2.A16, t3.loan_id, t3.account_id AS loan_account_id, t3.date AS loan_date, t3.amount, t3.duration, t3.payments, t3.status FROM account t1 INNER JOIN district t2 ON t1.district_id = t2.district_id INNER JOIN loan t3 ON t1.account_id = t3.account_id;
DROP VIEW IF EXISTS "cluster45_account_join_trans";
CREATE VIEW "cluster45_account_join_trans" AS 
SELECT t1.account_id AS account_account_id, t1.district_id, t1.frequency, t1.date AS account_date, t2.trans_id, t2.account_id AS trans_account_id, t2.date AS trans_date, t2.type, t2.operation, t2.amount, t2.balance, t2.k_symbol, t2.bank, t2.account FROM account t1 INNER JOIN trans t2 ON t1.account_id = t2.account_id;
DROP VIEW IF EXISTS "cluster46_card_join_disp_join_client";
CREATE VIEW "cluster46_card_join_disp_join_client" AS
SELECT
  t1.card_id, t1.type AS card_type, t1.issued,
  t1.disp_id AS card_disp_id,
  t2.disp_id AS disp_disp_id, t2.type AS disp_type,
  t2.account_id, t2.client_id AS disp_client_id,
  t3.client_id AS client_client_id, t3.gender, t3.birth_date, t3.district_id
FROM card t1
INNER JOIN disp t2 ON t1.disp_id = t2.disp_id
INNER JOIN client t3 ON t2.client_id = t3.client_id;
DROP VIEW IF EXISTS "cluster47_account_join_client_join_order";
CREATE VIEW "cluster47_account_join_client_join_order" AS 
SELECT t1.account_id AS account_account_id, t1.district_id AS account_district_id, t1.frequency, t1.date, t2.client_id, t2.gender, t2.birth_date, t2.district_id AS client_district_id, t3.order_id, t3.account_id AS order_account_id, t3.bank_to, t3.account_to, t3.amount, t3.k_symbol FROM account t1 INNER JOIN client t2 ON t1.district_id = t2.district_id INNER JOIN "order" t3 ON t1.account_id = t3.account_id;
DROP VIEW IF EXISTS "cluster48_posts_join_tags";
CREATE VIEW "cluster48_posts_join_tags" AS 
SELECT t1.PostTypeId, t1.AcceptedAnswerId, t1.CreaionDate, t1.Score, t1.ViewCount, t1.Body, t1.OwnerUserId, t1.LasActivityDate, t1.Title, t1.Tags, t1.AnswerCount, t1.CommentCount, t1.FavoriteCount, t1.LastEditorUserId, t1.LastEditDate, t1.CommunityOwnedDate, t1.ParentId, t1.ClosedDate, t1.OwnerDisplayName, t1.LastEditorDisplayName, t1.Id AS posts_Id, t2.Id AS tags_Id, t2.TagName, t2.Count, t2.ExcerptPostId, t2.WikiPostId FROM posts t1 INNER JOIN tags t2 ON t1.Id = t2.ExcerptPostId;
DROP VIEW IF EXISTS "cluster49_votes";
CREATE VIEW "cluster49_votes" AS 
SELECT Id, PostId, VoteTypeId, CreationDate, UserId, BountyAmount FROM votes;
DROP VIEW IF EXISTS "cluster4_client_join_district";
CREATE VIEW "cluster4_client_join_district" AS 
SELECT t1.client_id, t1.gender, t1.birth_date, t1.district_id AS client_district_id, t2.district_id AS district_district_id, t2.A2, t2.A3, t2.A4, t2.A5, t2.A6, t2.A7, t2.A8, t2.A9, t2.A10, t2.A11, t2.A12, t2.A13, t2.A14, t2.A15, t2.A16 FROM client t1 INNER JOIN district t2 ON t1.district_id = t2.district_id;
DROP VIEW IF EXISTS "cluster50_postlinks_join_posts";
CREATE VIEW "cluster50_postlinks_join_posts" AS 
SELECT t1.CreationDate AS postLinks_CreationDate, t1.RelatedPostId, t1.LinkTypeId, t1.Id AS postLinks_Id, t1.PostId AS postLinks_PostId, t2.Id AS posts_Id, t2.PostTypeId, t2.AcceptedAnswerId, t2.CreaionDate AS posts_CreaionDate, t2.Score, t2.ViewCount, t2.Body, t2.OwnerUserId, t2.LasActivityDate, t2.Title, t2.Tags, t2.AnswerCount, t2.CommentCount, t2.FavoriteCount, t2.LastEditorUserId, t2.LastEditDate, t2.CommunityOwnedDate, t2.ParentId, t2.ClosedDate, t2.OwnerDisplayName, t2.LastEditorDisplayName FROM postLinks t1 INNER JOIN posts t2 ON t1.PostId = t2.Id;
DROP VIEW IF EXISTS "cluster51_attribute_join_hero_attribute_join_publisher_join_superhero";
CREATE VIEW "cluster51_attribute_join_hero_attribute_join_publisher_join_superhero" AS 
SELECT t1.attribute_name, t1.id AS attribute_id, t2.hero_id AS hero_attribute_hero_id, t2.attribute_id AS hero_attribute_attribute_id, t2.attribute_value, t3.id AS publisher_id, t3.publisher_name, t4.id AS superhero_id, t4.superhero_name, t4.full_name, t4.gender_id, t4.eye_colour_id, t4.hair_colour_id, t4.skin_colour_id, t4.race_id, t4.publisher_id AS superhero_publisher_id, t4.alignment_id, t4.height_cm, t4.weight_kg FROM attribute t1 INNER JOIN hero_attribute t2 ON t1.id = t2.attribute_id INNER JOIN publisher t3 ON t1.id = t3.id INNER JOIN superhero t4 ON t1.id = t4.id;
DROP VIEW IF EXISTS "cluster52_attribute_join_gender_join_hero_attribute_join_superhero";
CREATE VIEW "cluster52_attribute_join_gender_join_hero_attribute_join_superhero" AS 
SELECT t1.attribute_name, t1.id AS attribute_id, t2.id AS gender_id, t2.gender, t3.hero_id AS hero_attribute_hero_id, t3.attribute_id AS hero_attribute_attribute_id, t3.attribute_value, t4.id AS superhero_id, t4.superhero_name, t4.full_name, t4.gender_id AS superhero_gender_id, t4.eye_colour_id, t4.hair_colour_id, t4.skin_colour_id, t4.race_id, t4.publisher_id, t4.alignment_id, t4.height_cm, t4.weight_kg FROM attribute t1 INNER JOIN gender t2 ON t1.id = t2.id INNER JOIN hero_attribute t3 ON t1.id = t3.attribute_id INNER JOIN superhero t4 ON t1.id = t4.id;
DROP VIEW IF EXISTS "cluster53_alignment_join_superhero";
CREATE VIEW "cluster53_alignment_join_superhero" AS 
SELECT t1.alignment, t1.id AS alignment_id, t2.id AS superhero_id, t2.superhero_name, t2.full_name, t2.gender_id, t2.eye_colour_id, t2.hair_colour_id, t2.skin_colour_id, t2.race_id, t2.publisher_id, t2.alignment_id AS superhero_alignment_id, t2.height_cm, t2.weight_kg FROM alignment t1 INNER JOIN superhero t2 ON t1.id = t2.alignment_id;
DROP VIEW IF EXISTS "cluster54_constructorstandings_join_constructors";
CREATE VIEW "cluster54_constructorstandings_join_constructors" AS 
SELECT t1.raceId, t1.points, t1.position, t1.positionText, t1.wins, t1.constructorStandingsId, t1.constructorId AS constructorStandings_constructorId, t2.constructorId AS constructors_constructorId, t2.constructorRef, t2.name, t2.nationality, t2.url FROM constructorStandings t1 INNER JOIN constructors t2 ON t1.constructorId = t2.constructorId;
DROP VIEW IF EXISTS "cluster55_races_join_seasons";
CREATE VIEW "cluster55_races_join_seasons" AS 
SELECT t1.round, t1.circuitId, t1.name, t1.date, t1.time, t1.url AS races_url, t1.raceId, t1.year AS races_year, t2.year AS seasons_year, t2.url AS seasons_url FROM races t1 INNER JOIN seasons t2 ON t1.year = t2.year;
DROP VIEW IF EXISTS "cluster56_drivers_join_laptimes";
CREATE VIEW "cluster56_drivers_join_laptimes" AS 
SELECT t1.driverRef, t1.number, t1.code, t1.forename, t1.surname, t1.dob, t1.nationality, t1.url, t1.driverId AS drivers_driverId, t2.raceId, t2.driverId AS lapTimes_driverId, t2.lap, t2.position, t2.time, t2.milliseconds FROM drivers t1 INNER JOIN lapTimes t2 ON t1.driverId = t2.driverId;
DROP VIEW IF EXISTS "cluster57_races_join_results_join_status";
CREATE VIEW "cluster57_races_join_results_join_status" AS 
SELECT t1.year, t1.round, t1.circuitId, t1.name, t1.date, t1.time AS races_time, t1.url, t1.raceId AS races_raceId, t2.resultId, t2.raceId AS results_raceId, t2.driverId, t2.constructorId, t2.number, t2.grid, t2.position, t2.positionText, t2.positionOrder, t2.points, t2.laps, t2.time AS results_time, t2.milliseconds, t2.fastestLap, t2.rank, t2.fastestLapTime, t2.fastestLapSpeed, t2.statusId AS results_statusId, t3.statusId AS status_statusId, t3.status FROM races t1 INNER JOIN results t2 ON t1.raceId = t2.raceId INNER JOIN status t3 ON t2.statusId = t3.statusId;
DROP VIEW IF EXISTS "cluster58_drivers_join_pitstops_join_races";
CREATE VIEW "cluster58_drivers_join_pitstops_join_races" AS 
SELECT t1.driverRef, t1.number, t1.code, t1.forename, t1.surname, t1.dob, t1.nationality, t1.url AS drivers_url, t1.driverId AS drivers_driverId, t2.raceId AS pitStops_raceId, t2.driverId AS pitStops_driverId, t2.stop, t2.lap, t2.time AS pitStops_time, t2.duration, t2.milliseconds AS pitStops_milliseconds, t3.raceId AS races_raceId, t3.year, t3.round, t3.circuitId, t3.name, t3.date, t3.time AS races_time, t3.url AS races_url FROM drivers t1 INNER JOIN pitStops t2 ON t1.driverId = t2.driverId INNER JOIN races t3 ON t2.raceId = t3.raceId;
DROP VIEW IF EXISTS "cluster59_circuits_join_races_join_pitstops_join_results";
CREATE VIEW "cluster59_circuits_join_races_join_pitstops_join_results" AS 
SELECT t1.circuitRef, t1.name AS circuits_name, t1.location, t1.country, t1.lat, t1.lng, t1.alt, t1.url AS circuits_url, t1.circuitId AS circuits_circuitId, t2.raceId AS races_raceId, t2.year, t2.round, t2.circuitId AS races_circuitId, t2.name AS races_name, t2.date, t2.time AS races_time, t2.url AS races_url, t3.raceId AS pitStops_raceId, t3.driverId AS pitStops_driverId, t3.stop, t3.lap, t3.time AS pitStops_time, t3.duration, t3.milliseconds AS pitStops_milliseconds, t4.resultId, t4.raceId AS results_raceId, t4.driverId AS results_driverId, t4.constructorId, t4.number, t4.grid, t4.position, t4.positionText, t4.positionOrder, t4.points, t4.laps, t4.time AS results_time, t4.milliseconds AS results_milliseconds, t4.fastestLap, t4.rank, t4.fastestLapTime, t4.fastestLapSpeed, t4.statusId FROM circuits t1 INNER JOIN races t2 ON t1.circuitId = t2.circuitId INNER JOIN pitStops t3 ON t2.raceId = t3.raceId INNER JOIN results t4 ON t2.raceId = t4.raceId AND t3.driverId = t4.driverId;
DROP VIEW IF EXISTS "cluster5_atom_join_bond";
CREATE VIEW "cluster5_atom_join_bond" AS 
SELECT t1.atom_id, t1.element, t1.molecule_id AS atom_molecule_id, t2.bond_id, t2.bond_type, t2.molecule_id AS bond_molecule_id FROM atom t1 INNER JOIN bond t2 ON t1.molecule_id = t2.molecule_id;
DROP VIEW IF EXISTS "cluster60_country_join_league";
CREATE VIEW "cluster60_country_join_league" AS
SELECT 
  t1.id AS Country_id, t1.name AS Country_name,
  t2.id AS League_id, t2.country_id AS League_country_id, t2.name AS League_name
FROM Country t1 INNER JOIN League t2 ON t1.id = t2.country_id;
DROP VIEW IF EXISTS "cluster61_country_join_match_join_player";
CREATE VIEW "cluster61_country_join_match_join_player" AS
SELECT 
    t1.id AS Country_id, t1.name AS Country_name,
    t2.id AS Match_id, t2.country_id AS Match_country_id, t2.league_id, t2.season, t2.stage, t2.date, t2.match_api_id, t2.home_team_api_id, t2.away_team_api_id, t2.home_team_goal, t2.away_team_goal, 
    t2.home_player_X1, t2.home_player_X2, t2.home_player_X3, t2.home_player_X4, t2.home_player_X5, t2.home_player_X6, t2.home_player_X7, t2.home_player_X8, t2.home_player_X9, t2.home_player_X10, t2.home_player_X11, 
    t2.away_player_X1, t2.away_player_X2, t2.away_player_X3, t2.away_player_X4, t2.away_player_X5, t2.away_player_X6, t2.away_player_X7, t2.away_player_X8, t2.away_player_X9, t2.away_player_X10, t2.away_player_X11, 
    t2.home_player_Y1, t2.home_player_Y2, t2.home_player_Y3, t2.home_player_Y4, t2.home_player_Y5, t2.home_player_Y6, t2.home_player_Y7, t2.home_player_Y8, t2.home_player_Y9, t2.home_player_Y10, t2.home_player_Y11, 
    t2.away_player_Y1, t2.away_player_Y2, t2.away_player_Y3, t2.away_player_Y4, t2.away_player_Y5, t2.away_player_Y6, t2.away_player_Y7, t2.away_player_Y8, t2.away_player_Y9, t2.away_player_Y10, t2.away_player_Y11, 
    t2.home_player_1, t2.home_player_2, t2.home_player_3, t2.home_player_4, t2.home_player_5, t2.home_player_6, t2.home_player_7, t2.home_player_8, t2.home_player_9, t2.home_player_10, t2.home_player_11, 
    t2.away_player_1, t2.away_player_2, t2.away_player_3, t2.away_player_4, t2.away_player_5, t2.away_player_6, t2.away_player_7, t2.away_player_8, t2.away_player_9, t2.away_player_10, t2.away_player_11, 
    t2.goal, t2.shoton, t2.shotoff, t2.foulcommit, t2.card, t2."cross", t2.corner, t2.possession, 
    t2.B365H, t2.B365D, t2.B365A, t2.BWH, t2.BWD, t2.BWA, t2.IWH, t2.IWD, t2.IWA, t2.LBH, t2.LBD, t2.LBA, t2.PSH, t2.PSD, t2.PSA, t2.WHH, t2.WHD, t2.WHA, t2.SJH, t2.SJD, t2.SJA, t2.VCH, t2.VCD, t2.VCA, t2.GBH, t2.GBD, t2.GBA, t2.BSH, t2.BSD, t2.BSA,
    t3.id AS Player_id, t3.player_api_id, t3.player_name, t3.player_fifa_api_id, t3.birthday, t3.height, t3.weight
FROM Country t1 
INNER JOIN "Match" t2 ON t1.id = t2.country_id
INNER JOIN Player t3 ON t2.home_player_1 = t3.player_api_id;
DROP VIEW IF EXISTS "cluster62_attendance_join_event_join_member";
CREATE VIEW "cluster62_attendance_join_event_join_member" AS 
SELECT t1.link_to_event AS attendance_link_to_event, t1.link_to_member AS attendance_link_to_member, t2.event_id, t2.event_name, t2.event_date, t2.type, t2.notes, t2.location, t2.status, t3.member_id, t3.first_name, t3.last_name, t3.email, t3.position, t3.t_shirt_size, t3.phone, t3.zip, t3.link_to_major FROM attendance t1 INNER JOIN event t2 ON t1.link_to_event = t2.event_id INNER JOIN member t3 ON t1.link_to_member = t3.member_id;
DROP VIEW IF EXISTS "cluster63_income_join_member";
CREATE VIEW "cluster63_income_join_member" AS 
SELECT t1.income_id, t1.date_received, t1.amount, t1.source, t1.notes, t1.link_to_member AS income_link_to_member, t2.member_id AS member_member_id, t2.first_name, t2.last_name, t2.email, t2.position, t2.t_shirt_size, t2.phone, t2.zip, t2.link_to_major FROM income t1 INNER JOIN member t2 ON t1.link_to_member = t2.member_id;
DROP VIEW IF EXISTS "cluster64_customers_join_transactions_1k_join_products";
CREATE VIEW "cluster64_customers_join_transactions_1k_join_products" AS 
SELECT t1.Segment, t1.Currency, t1.CustomerID AS customers_CustomerID, t2.TransactionID, t2.Date, t2.Time, t2.CardID, t2.GasStationID, t2.Amount, t2.Price, t2.CustomerID AS transactions_1k_CustomerID, t2.ProductID AS transactions_1k_ProductID, t3.ProductID AS products_ProductID, t3.Description FROM customers t1 INNER JOIN transactions_1k t2 ON t1.CustomerID = t2.CustomerID INNER JOIN products t3 ON t2.ProductID = t3.ProductID;
DROP VIEW IF EXISTS "cluster6_bond_join_molecule";
CREATE VIEW "cluster6_bond_join_molecule" AS 
SELECT t1.bond_id, t1.bond_type, t1.molecule_id AS bond_molecule_id, t2.molecule_id AS molecule_molecule_id, t2.label FROM bond t1 INNER JOIN molecule t2 ON t1.molecule_id = t2.molecule_id;
DROP VIEW IF EXISTS "cluster7_atom_join_connected";
CREATE VIEW "cluster7_atom_join_connected" AS 
SELECT t1.molecule_id, t1.element, t1.atom_id AS atom_atom_id, t2.atom_id AS connected_atom_id, t2.atom_id2, t2.bond_id FROM atom t1 INNER JOIN connected t2 ON t1.atom_id = t2.atom_id;
DROP VIEW IF EXISTS "cluster8_atom_join_molecule";
CREATE VIEW "cluster8_atom_join_molecule" AS 
SELECT t1.atom_id, t1.element, t1.molecule_id AS atom_molecule_id, t2.molecule_id AS molecule_molecule_id, t2.label FROM atom t1 INNER JOIN molecule t2 ON t1.molecule_id = t2.molecule_id;
DROP VIEW IF EXISTS "cluster9_bond_join_connected";
CREATE VIEW "cluster9_bond_join_connected" AS 
SELECT t1.molecule_id, t1.bond_type, t1.bond_id AS bond_bond_id, t2.atom_id, t2.atom_id2, t2.bond_id AS connected_bond_id FROM bond t1 INNER JOIN connected t2 ON t1.bond_id = t2.bond_id;

-- ==== renamed_views (64) =======================================
DROP VIEW IF EXISTS "workload_updated_cluster10_Chem_Atoms_join_Chem_Bonds_join_Chem_Molecules";
CREATE VIEW workload_updated_cluster10_Chem_Atoms_join_Chem_Bonds_join_Chem_Molecules AS
SELECT 
    T1.atom_id, T1.molecule_id, T1.element_symbol,
    T2.bond_id, T2.molecule_id AS Chem_Bonds_molecule_id, T2.bond_symbol,
    T3.molecule_id AS Chem_Molecules_molecule_id, T3.carcinogenic_flag
FROM Chem_Atoms AS T1
JOIN Chem_Molecules AS T3 ON T1.molecule_id = T3.molecule_id
JOIN Chem_Bonds AS T2 ON T3.molecule_id = T2.molecule_id;
DROP VIEW IF EXISTS "workload_updated_cluster11_MTG_Cards_join_MTG_Legality";
CREATE VIEW workload_updated_cluster11_MTG_Cards_join_MTG_Legality AS
SELECT 
    T1.card_id, T1.illustrator_name, T1.ascii_name, T1.availability, T1.border_color, T1.cardKingdomFoilId, T1.cardKingdomId, T1.colorIdentity, T1.colorIndicator, T1.colors, T1.mana_cost, T1.duel_deck_id, T1.edhrec_rank, T1.faceConvertedManaCost, T1.faceName, T1.flavorName, T1.flavorText, T1.frameEffects, T1.frameVersion, T1.hand_modifier, T1.hasAlternativeDeckLimit, T1.hasContentWarning, T1.is_foil, T1.hasNonFoil, T1.isAlternative, T1.is_full_art, T1.isOnlineOnly, T1.isOversized, T1.is_promo, T1.is_reprint, T1.isReserved, T1.isStarter, T1.is_story_spotlight, T1.is_textless, T1.isTimeshifted, T1.keywords, T1.layout, T1.leadershipSkills, T1.life_modifier, T1.loyalty, T1.mana_cost_code, T1.mcmId, T1.mcmMetaId, T1.mtgArenaId, T1.mtgjsonV4Id, T1.mtgoFoilId, T1.mtgoId, T1.multiverseId, T1.card_name, T1.collector_number, T1.release_date, T1.original_rules, T1.original_type_line, T1.otherFaceIds, T1.power, T1.printings, T1.promo_type, T1.purchaseUrls, T1.rarity, T1.scryfallId, T1.scryfallIllustrationId, T1.scryfallOracleId, T1.set_code, T1.side, T1.subtypes, T1.supertypes, T1.tcgplayerProductId, T1.rules_text, T1.toughness, T1.full_type_line, T1.main_type, T1.card_uuid, T1.variations, T1.watermark,
    T2.legality_id, T2.format, T2.legality_status, T2.uuid
FROM MTG_Cards AS T1
JOIN MTG_Legality AS T2 ON T1.card_uuid = T2.uuid;
DROP VIEW IF EXISTS "workload_updated_cluster12_MTG_Cards_join_MTG_Rulings";
CREATE VIEW workload_updated_cluster12_MTG_Cards_join_MTG_Rulings AS
SELECT 
    T1.card_id, T1.illustrator_name, T1.ascii_name, T1.availability, T1.border_color, T1.cardKingdomFoilId, T1.cardKingdomId, T1.colorIdentity, T1.colorIndicator, T1.colors, T1.mana_cost, T1.duel_deck_id, T1.edhrec_rank, T1.faceConvertedManaCost, T1.faceName, T1.flavorName, T1.flavorText, T1.frameEffects, T1.frameVersion, T1.hand_modifier, T1.hasAlternativeDeckLimit, T1.hasContentWarning, T1.is_foil, T1.hasNonFoil, T1.isAlternative, T1.is_full_art, T1.isOnlineOnly, T1.isOversized, T1.is_promo, T1.is_reprint, T1.isReserved, T1.isStarter, T1.is_story_spotlight, T1.is_textless, T1.isTimeshifted, T1.keywords, T1.layout, T1.leadershipSkills, T1.life_modifier, T1.loyalty, T1.mana_cost_code, T1.mcmId, T1.mcmMetaId, T1.mtgArenaId, T1.mtgjsonV4Id, T1.mtgoFoilId, T1.mtgoId, T1.multiverseId, T1.card_name, T1.collector_number, T1.release_date, T1.original_rules, T1.original_type_line, T1.otherFaceIds, T1.power, T1.printings, T1.promo_type, T1.purchaseUrls, T1.rarity, T1.scryfallId, T1.scryfallIllustrationId, T1.scryfallOracleId, T1.set_code, T1.side, T1.subtypes, T1.supertypes, T1.tcgplayerProductId, T1.rules_text, T1.toughness, T1.full_type_line, T1.main_type, T1.card_uuid, T1.variations, T1.watermark,
    T2.ruling_id, T2.ruling_date, T2.ruling_text, T2.uuid AS MTG_Rulings_uuid
FROM MTG_Cards AS T1
JOIN MTG_Rulings AS T2 ON T1.card_uuid = T2.uuid;
DROP VIEW IF EXISTS "workload_updated_cluster13_MTG_Cards_join_MTG_Set_Translations";
CREATE VIEW workload_updated_cluster13_MTG_Cards_join_MTG_Set_Translations AS
SELECT 
    T1.card_id, T1.illustrator_name, T1.ascii_name, T1.availability, T1.border_color, T1.cardKingdomFoilId, T1.cardKingdomId, T1.colorIdentity, T1.colorIndicator, T1.colors, T1.mana_cost, T1.duel_deck_id, T1.edhrec_rank, T1.faceConvertedManaCost, T1.faceName, T1.flavorName, T1.flavorText, T1.frameEffects, T1.frameVersion, T1.hand_modifier, T1.hasAlternativeDeckLimit, T1.hasContentWarning, T1.is_foil, T1.hasNonFoil, T1.isAlternative, T1.is_full_art, T1.isOnlineOnly, T1.isOversized, T1.is_promo, T1.is_reprint, T1.isReserved, T1.isStarter, T1.is_story_spotlight, T1.is_textless, T1.isTimeshifted, T1.keywords, T1.layout, T1.leadershipSkills, T1.life_modifier, T1.loyalty, T1.mana_cost_code, T1.mcmId, T1.mcmMetaId, T1.mtgArenaId, T1.mtgjsonV4Id, T1.mtgoFoilId, T1.mtgoId, T1.multiverseId, T1.card_name, T1.collector_number, T1.release_date, T1.original_rules, T1.original_type_line, T1.otherFaceIds, T1.power, T1.printings, T1.promo_type, T1.purchaseUrls, T1.rarity, T1.scryfallId, T1.scryfallIllustrationId, T1.scryfallOracleId, T1.set_code, T1.side, T1.subtypes, T1.supertypes, T1.tcgplayerProductId, T1.rules_text, T1.toughness, T1.full_type_line, T1.main_type, T1.card_uuid, T1.variations, T1.watermark,
    T2.translation_id, T2.language, T2.set_code AS MTG_Set_Translations_set_code, T2.translation
FROM MTG_Cards AS T1
JOIN MTG_Set_Translations AS T2 ON T1.set_code = T2.set_code;
DROP VIEW IF EXISTS "workload_updated_cluster14_MTG_Card_Foreign_Data_join_MTG_Cards";
CREATE VIEW workload_updated_cluster14_MTG_Card_Foreign_Data_join_MTG_Cards AS
SELECT 
    T1.foreign_data_id, T1.flavor_text, T1.language, T1.multiverse_id, T1.card_name, T1.rules_text, T1.card_type, T1.uuid,
    T2.card_id, T2.illustrator_name, T2.ascii_name, T2.availability, T2.border_color, T2.cardKingdomFoilId, T2.cardKingdomId, T2.colorIdentity, T2.colorIndicator, T2.colors, T2.mana_cost, T2.duel_deck_id, T2.edhrec_rank, T2.faceConvertedManaCost, T2.faceName, T2.flavorName, T2.flavorText AS MTG_Cards_flavorText, T2.frameEffects, T2.frameVersion, T2.hand_modifier, T2.hasAlternativeDeckLimit, T2.hasContentWarning, T2.is_foil, T2.hasNonFoil, T2.isAlternative, T2.is_full_art, T2.isOnlineOnly, T2.isOversized, T2.is_promo, T2.is_reprint, T2.isReserved, T2.isStarter, T2.is_story_spotlight, T2.is_textless, T2.isTimeshifted, T2.keywords, T2.layout, T2.leadershipSkills, T2.life_modifier, T2.loyalty, T2.mana_cost_code, T2.mcmId, T2.mcmMetaId, T2.mtgArenaId, T2.mtgjsonV4Id, T2.mtgoFoilId, T2.mtgoId, T2.multiverseId AS MTG_Cards_multiverseId, T2.card_name AS MTG_Cards_card_name, T2.collector_number, T2.release_date, T2.original_rules, T2.original_type_line, T2.otherFaceIds, T2.power, T2.printings, T2.promo_type, T2.purchaseUrls, T2.rarity, T2.scryfallId, T2.scryfallIllustrationId, T2.scryfallOracleId, T2.set_code, T2.side, T2.subtypes, T2.supertypes, T2.tcgplayerProductId, T2.rules_text AS MTG_Cards_rules_text, T2.toughness, T2.full_type_line, T2.main_type, T2.card_uuid, T2.variations, T2.watermark
FROM MTG_Card_Foreign_Data AS T1
JOIN MTG_Cards AS T2 ON T1.uuid = T2.card_uuid;
DROP VIEW IF EXISTS "workload_updated_cluster15_MTG_Set_Translations_join_MTG_Sets";
CREATE VIEW workload_updated_cluster15_MTG_Set_Translations_join_MTG_Sets AS
SELECT 
    T1.translation_id, T1.language, T1.set_code, T1.translation,
    T2.set_id, T2.base_set_size, T2.block, T2.booster, T2.set_code AS MTG_Sets_set_code, T2.is_foil_only, T2.is_foreign_only, T2.is_nonfoil_only, T2.is_online_only, T2.is_partial_preview, T2.keyrune_code, T2.mcm_id, T2.mcm_id_extras, T2.mcm_name, T2.mtgo_code, T2.set_name, T2.parent_set_code, T2.release_date, T2.tcgplayer_group_id, T2.total_set_size, T2.set_type
FROM MTG_Set_Translations AS T1
JOIN MTG_Sets AS T2 ON T1.set_code = T2.set_code;
DROP VIEW IF EXISTS "workload_updated_cluster16_MTG_Cards_join_MTG_Sets";
CREATE VIEW workload_updated_cluster16_MTG_Cards_join_MTG_Sets AS
SELECT 
    T1.card_id, T1.illustrator_name, T1.ascii_name, T1.availability, T1.border_color, T1.cardKingdomFoilId, T1.cardKingdomId, T1.colorIdentity, T1.colorIndicator, T1.colors, T1.mana_cost, T1.duel_deck_id, T1.edhrec_rank, T1.faceConvertedManaCost, T1.faceName, T1.flavorName, T1.flavorText, T1.frameEffects, T1.frameVersion, T1.hand_modifier, T1.hasAlternativeDeckLimit, T1.hasContentWarning, T1.is_foil, T1.hasNonFoil, T1.isAlternative, T1.is_full_art, T1.isOnlineOnly, T1.isOversized, T1.is_promo, T1.is_reprint, T1.isReserved, T1.isStarter, T1.is_story_spotlight, T1.is_textless, T1.isTimeshifted, T1.keywords, T1.layout, T1.leadershipSkills, T1.life_modifier, T1.loyalty, T1.mana_cost_code, T1.mcmId, T1.mcmMetaId, T1.mtgArenaId, T1.mtgjsonV4Id, T1.mtgoFoilId, T1.mtgoId, T1.multiverseId, T1.card_name, T1.collector_number, T1.release_date, T1.original_rules, T1.original_type_line, T1.otherFaceIds, T1.power, T1.printings, T1.promo_type, T1.purchaseUrls, T1.rarity, T1.scryfallId, T1.scryfallIllustrationId, T1.scryfallOracleId, T1.set_code, T1.side, T1.subtypes, T1.supertypes, T1.tcgplayerProductId, T1.rules_text, T1.toughness, T1.full_type_line, T1.main_type, T1.card_uuid, T1.variations, T1.watermark,
    T2.set_id, T2.base_set_size, T2.block, T2.booster, T2.set_code AS MTG_Sets_set_code, T2.is_foil_only, T2.is_foreign_only, T2.is_nonfoil_only, T2.is_online_only, T2.is_partial_preview, T2.keyrune_code, T2.mcm_id, T2.mcm_id_extras, T2.mcm_name, T2.mtgo_code, T2.set_name, T2.parent_set_code, T2.release_date AS MTG_Sets_release_date, T2.tcgplayer_group_id, T2.total_set_size, T2.set_type
FROM MTG_Cards AS T1
JOIN MTG_Sets AS T2 ON T1.set_code = T2.set_code;
DROP VIEW IF EXISTS "workload_updated_cluster17_Forum_Posts_join_Forum_Users";
CREATE VIEW workload_updated_cluster17_Forum_Posts_join_Forum_Users AS
SELECT 
    T1.post_id, T1.post_type_id, T1.accepted_answer_id, T1.created_at, T1.post_score, T1.view_count, T1.post_content, T1.user_id, T1.last_activity_at, T1.post_title, T1.post_tags, T1.answer_count, T1.comment_count, T1.favorite_count, T1.last_editor_id, T1.last_edit_date, T1.community_owned_date, T1.parent_post_id, T1.closed_at, T1.owner_name, T1.last_editor_name,
    T2.user_id AS Forum_Users_user_id, T2.reputation_score, T2.account_created_at, T2.display_name, T2.last_access_at, T2.website_url, T2.user_location, T2.bio_text, T2.profile_views, T2.total_up_votes, T2.total_down_votes, T2.global_account_id, T2.user_age, T2.profile_image_url
FROM Forum_Posts AS T1
JOIN Forum_Users AS T2 ON T1.user_id = T2.user_id;
DROP VIEW IF EXISTS "workload_updated_cluster18_Forum_Badges_join_Forum_Users";
CREATE VIEW workload_updated_cluster18_Forum_Badges_join_Forum_Users AS
SELECT 
    T1.badge_id, T1.user_id, T1.badge_name, T1.awarded_at,
    T2.user_id AS Forum_Users_user_id, T2.reputation_score, T2.account_created_at, T2.display_name, T2.last_access_at, T2.website_url, T2.user_location, T2.bio_text, T2.profile_views, T2.total_up_votes, T2.total_down_votes, T2.global_account_id, T2.user_age, T2.profile_image_url
FROM Forum_Badges AS T1
JOIN Forum_Users AS T2 ON T1.user_id = T2.user_id;
DROP VIEW IF EXISTS "workload_updated_cluster19_Forum_Comments_join_Forum_Posts";
CREATE VIEW workload_updated_cluster19_Forum_Comments_join_Forum_Posts AS
SELECT 
    T1.comment_id, T1.post_id, T1.comment_score, T1.comment_text, T1.created_at, T1.user_id, T1.user_name,
    T2.post_id AS Forum_Posts_post_id, T2.post_type_id, T2.accepted_answer_id, T2.created_at AS Forum_Posts_created_at, T2.post_score, T2.view_count, T2.post_content, T2.user_id AS Forum_Posts_user_id, T2.last_activity_at, T2.post_title, T2.post_tags, T2.answer_count, T2.comment_count AS Forum_Posts_comment_count, T2.favorite_count, T2.last_editor_id, T2.last_edit_date, T2.community_owned_date, T2.parent_post_id, T2.closed_at, T2.owner_name, T2.last_editor_name
FROM Forum_Comments AS T1
JOIN Forum_Posts AS T2 ON T1.post_id = T2.post_id;
DROP VIEW IF EXISTS "workload_updated_cluster1_Education_Lunch_Aid_join_Education_Schools";
CREATE VIEW workload_updated_cluster1_Education_Lunch_Aid_join_Education_Schools AS
SELECT 
    T1.school_cds_code, T1.academic_year, T1.county_code, T1.district_code, T1.school_code, T1.county_name, T1.district_name, T1.school_name, T1.district_type, T1.school_type, T1.educational_option_type, T1.nslp_provision_status, T1.is_charter_school, T1.charter_school_number, T1.charter_funding_type, T1.irc_code, T1.grade_low, T1.grade_high, T1.enrollment_k12, T1.free_meal_count_k12, T1.percent_eligible_free_k12, T1.frpm_count_k12, T1.percent_eligible_frpm_k12, T1.enrollment_ages_5_17, T1.free_meal_count_ages_5_17, T1.percent_eligible_free_ages_5_17, T1.frpm_count_ages_5_17, T1.percent_eligible_frpm_ages_5_17, T1.calpads_certification_status,
    T2.school_cds_code AS Education_Schools_school_cds_code, T2.nces_district_id, T2.nces_school_id, T2.school_status, T2.county_name AS Education_Schools_county_name, T2.district_name AS Education_Schools_district_name, T2.school_name AS Education_Schools_school_name, T2.street_address, T2.street_address_abbrev, T2.city, T2.zip_code, T2.state, T2.mailing_street, T2.mailing_street_abbrev, T2.mailing_city, T2.mailing_zip, T2.mailing_state, T2.phone_number, T2.phone_extension, T2.website_url, T2.date_opened, T2.date_closed, T2.is_charter_flag, T2.charter_number, T2.funding_type, T2.district_ownership_code, T2.district_ownership_type, T2.school_ownership_code, T2.school_ownership_type, T2.ed_ops_code, T2.ed_ops_name, T2.eil_code, T2.eil_name, T2.grades_offered, T2.grades_served, T2.is_virtual_code, T2.is_magnet_flag, T2.latitude, T2.longitude, T2.admin_first_name_1, T2.admin_last_name_1, T2.admin_email_1, T2.admin_first_name_2, T2.admin_last_name_2, T2.admin_email_2, T2.admin_first_name_3, T2.admin_last_name_3, T2.admin_email_3, T2.last_update_date
FROM Education_Lunch_Aid AS T1
JOIN Education_Schools AS T2 ON T1.school_cds_code = T2.school_cds_code;
DROP VIEW IF EXISTS "workload_updated_cluster20_Forum_History_join_Forum_Posts_join_Forum_Users";
CREATE VIEW workload_updated_cluster20_Forum_History_join_Forum_Posts_join_Forum_Users AS
SELECT 
    T1.history_id, T1.history_type_id, T1.post_id, T1.revision_id, T1.created_at, T1.user_id, T1.content_text, T1.edit_comment, T1.user_name,
    T2.post_id AS Forum_Posts_post_id, T2.post_type_id, T2.accepted_answer_id, T2.created_at AS Forum_Posts_created_at, T2.post_score, T2.view_count, T2.post_content, T2.user_id AS Forum_Posts_user_id, T2.last_activity_at, T2.post_title, T2.post_tags, T2.answer_count, T2.comment_count, T2.favorite_count, T2.last_editor_id, T2.last_edit_date, T2.community_owned_date, T2.parent_post_id, T2.closed_at, T2.owner_name AS Forum_Posts_owner_name, T2.last_editor_name,
    T3.user_id AS Forum_Users_user_id, T3.reputation_score, T3.account_created_at, T3.display_name, T3.last_access_at, T3.website_url, T3.user_location, T3.bio_text, T3.profile_views, T3.total_up_votes, T3.total_down_votes, T3.global_account_id, T3.user_age, T3.profile_image_url
FROM Forum_History AS T1
JOIN Forum_Users AS T3 ON T1.user_id = T3.user_id
JOIN Forum_Posts AS T2 ON T1.post_id = T2.post_id;
DROP VIEW IF EXISTS "workload_updated_cluster21_Hero_Power_Map_join_Hero_Profiles_join_Hero_Superpowers";
CREATE VIEW workload_updated_cluster21_Hero_Power_Map_join_Hero_Profiles_join_Hero_Superpowers AS
SELECT 
    T1.hero_id, T1.power_id,
    T2.hero_id AS Hero_Profiles_hero_id, T2.superhero_name, T2.full_name, T2.gender_id, T2.eye_colour_id, T2.hair_colour_id, T2.skin_colour_id, T2.race_id, T2.publisher_id, T2.alignment_id, T2.height_cm, T2.weight_kg,
    T3.superpower_id, T3.power_name
FROM Hero_Power_Map AS T1
JOIN Hero_Profiles AS T2 ON T1.hero_id = T2.hero_id
JOIN Hero_Superpowers AS T3 ON T1.power_id = T3.superpower_id;
DROP VIEW IF EXISTS "workload_updated_cluster22_Hero_Profiles_join_Hero_Publishers";
CREATE VIEW workload_updated_cluster22_Hero_Profiles_join_Hero_Publishers AS
SELECT 
    T1.hero_id, T1.superhero_name, T1.full_name, T1.gender_id, T1.eye_colour_id, T1.hair_colour_id, T1.skin_colour_id, T1.race_id, T1.publisher_id, T1.alignment_id, T1.height_cm, T1.weight_kg,
    T2.publisher_id AS Hero_Publishers_publisher_id, T2.publisher_name
FROM Hero_Profiles AS T1
JOIN Hero_Publishers AS T2 ON T1.publisher_id = T2.publisher_id;
DROP VIEW IF EXISTS "workload_updated_cluster23_Hero_Colors_join_Hero_Profiles";
CREATE VIEW workload_updated_cluster23_Hero_Colors_join_Hero_Profiles AS
SELECT 
    T1.colour_id, T1.colour,
    T2.hero_id, T2.superhero_name, T2.full_name, T2.gender_id, T2.eye_colour_id, T2.hair_colour_id, T2.skin_colour_id, T2.race_id, T2.publisher_id, T2.alignment_id, T2.height_cm, T2.weight_kg
FROM Hero_Colors AS T1
JOIN Hero_Profiles AS T2 ON T1.colour_id = T2.eye_colour_id;
DROP VIEW IF EXISTS "workload_updated_cluster24_Hero_Profiles_join_Hero_Races";
CREATE VIEW workload_updated_cluster24_Hero_Profiles_join_Hero_Races AS
SELECT 
    T1.hero_id, T1.superhero_name, T1.full_name, T1.gender_id, T1.eye_colour_id, T1.hair_colour_id, T1.skin_colour_id, T1.race_id, T1.publisher_id, T1.alignment_id, T1.height_cm, T1.weight_kg,
    T2.race_id AS Hero_Races_race_id, T2.race
FROM Hero_Profiles AS T1
JOIN Hero_Races AS T2 ON T1.race_id = T2.race_id;
DROP VIEW IF EXISTS "workload_updated_cluster25_F1_Races_join_F1_Tracks";
CREATE VIEW workload_updated_cluster25_F1_Races_join_F1_Tracks AS
SELECT 
    T1.race_id, T1.season_year, T1.round_number, T1.circuit_id, T1.race_name, T1.race_date, T1.race_time, T1.url,
    T2.circuit_id AS F1_Tracks_circuit_id, T2.circuit_ref, T2.circuit_name, T2.location, T2.country, T2.latitude, T2.longitude, T2.altitude, T2.url AS F1_Tracks_url
FROM F1_Races AS T1
JOIN F1_Tracks AS T2 ON T1.circuit_id = T2.circuit_id;
DROP VIEW IF EXISTS "workload_updated_cluster26_F1_Drivers_join_F1_Qualifying";
CREATE VIEW workload_updated_cluster26_F1_Drivers_join_F1_Qualifying AS
SELECT 
    T1.driver_id, T1.driver_ref, T1.driver_number, T1.driver_code, T1.first_name, T1.last_name, T1.birth_date, T1.nationality, T1.url,
    T2.qualifying_id, T2.race_id, T2.driver_id AS F1_Qualifying_driver_id, T2.constructor_id, T2.car_number, T2.position, T2.q1, T2.q2, T2.q3
FROM F1_Drivers AS T1
JOIN F1_Qualifying AS T2 ON T1.driver_id = T2.driver_id;
DROP VIEW IF EXISTS "workload_updated_cluster27_F1_Races_join_F1_Results";
CREATE VIEW workload_updated_cluster27_F1_Races_join_F1_Results AS
SELECT 
    T1.race_id, T1.season_year, T1.round_number, T1.circuit_id, T1.race_name, T1.race_date, T1.race_time, T1.url,
    T2.result_id, T2.race_id AS F1_Results_race_id, T2.driver_id, T2.constructor_id, T2.car_number, T2.start_position, T2.finish_position, T2.finish_position_text, T2.finish_order, T2.points, T2.laps_completed, T2.finish_time, T2.milliseconds, T2.fastest_lap_number, T2.fastest_lap_rank, T2.fastest_lap_time, T2.fastest_lap_speed, T2.status_id
FROM F1_Races AS T1
JOIN F1_Results AS T2 ON T1.race_id = T2.race_id;
DROP VIEW IF EXISTS "workload_updated_cluster28_F1_Drivers_join_F1_Results";
CREATE VIEW workload_updated_cluster28_F1_Drivers_join_F1_Results AS
SELECT 
    T1.driver_id, T1.driver_ref, T1.driver_number, T1.driver_code, T1.first_name, T1.last_name, T1.birth_date, T1.nationality, T1.url,
    T2.result_id, T2.race_id, T2.driver_id AS F1_Results_driver_id, T2.constructor_id, T2.car_number, T2.start_position, T2.finish_position, T2.finish_position_text, T2.finish_order, T2.points, T2.laps_completed, T2.finish_time, T2.milliseconds, T2.fastest_lap_number, T2.fastest_lap_rank, T2.fastest_lap_time, T2.fastest_lap_speed, T2.status_id
FROM F1_Drivers AS T1
JOIN F1_Results AS T2 ON T1.driver_id = T2.driver_id;
DROP VIEW IF EXISTS "workload_updated_cluster29_F1_Driver_Standings_join_F1_Drivers_join_F1_Races";
CREATE VIEW workload_updated_cluster29_F1_Driver_Standings_join_F1_Drivers_join_F1_Races AS
SELECT 
    T1.standing_id, T1.race_id, T1.driver_id, T1.points, T1.position, T1.position_text, T1.wins,
    T2.driver_id AS F1_Drivers_driver_id, T2.driver_ref, T2.driver_number, T2.driver_code, T2.first_name, T2.last_name, T2.birth_date, T2.nationality, T2.url AS F1_Drivers_url,
    T3.race_id AS F1_Races_race_id, T3.season_year, T3.round_number, T3.circuit_id, T3.race_name, T3.race_date, T3.race_time, T3.url AS F1_Races_url
FROM F1_Driver_Standings AS T1
JOIN F1_Drivers AS T2 ON T1.driver_id = T2.driver_id
JOIN F1_Races AS T3 ON T1.race_id = T3.race_id;
DROP VIEW IF EXISTS "workload_updated_cluster2_Education_SAT_Stats_join_Education_Schools";
CREATE VIEW workload_updated_cluster2_Education_SAT_Stats_join_Education_Schools AS
SELECT 
    T1.school_cds_code, T1.record_type, T1.school_name, T1.district_name, T1.county_name, T1.grade_12_enrollment, T1.total_test_takers, T1.avg_score_reading, T1.avg_score_math, T1.avg_score_writing, T1.num_scores_ge_1500,
    T2.school_cds_code AS Education_Schools_school_cds_code, T2.nces_district_id, T2.nces_school_id, T2.school_status, T2.county_name AS Education_Schools_county_name, T2.district_name AS Education_Schools_district_name, T2.school_name AS Education_Schools_school_name, T2.street_address, T2.street_address_abbrev, T2.city, T2.zip_code, T2.state, T2.mailing_street, T2.mailing_street_abbrev, T2.mailing_city, T2.mailing_zip, T2.mailing_state, T2.phone_number, T2.phone_extension, T2.website_url, T2.date_opened, T2.date_closed, T2.is_charter_flag, T2.charter_number, T2.funding_type, T2.district_ownership_code, T2.district_ownership_type, T2.school_ownership_code, T2.school_ownership_type, T2.ed_ops_code, T2.ed_ops_name, T2.eil_code, T2.eil_name, T2.grades_offered, T2.grades_served, T2.is_virtual_code, T2.is_magnet_flag, T2.latitude, T2.longitude, T2.admin_first_name_1, T2.admin_last_name_1, T2.admin_email_1, T2.admin_first_name_2, T2.admin_last_name_2, T2.admin_email_2, T2.admin_first_name_3, T2.admin_last_name_3, T2.admin_email_3, T2.last_update_date
FROM Education_SAT_Stats AS T1
JOIN Education_Schools AS T2 ON T1.school_cds_code = T2.school_cds_code;
DROP VIEW IF EXISTS "workload_updated_cluster30_F1_Drivers_join_F1_Races_join_F1_Results";
CREATE VIEW workload_updated_cluster30_F1_Drivers_join_F1_Races_join_F1_Results AS
SELECT 
    T1.driver_id, T1.driver_ref, T1.driver_number, T1.driver_code, T1.first_name, T1.last_name, T1.birth_date, T1.nationality, T1.url,
    T2.race_id AS F1_Races_race_id, T2.season_year, T2.round_number, T2.circuit_id, T2.race_name, T2.race_date, T2.race_time, T2.url AS F1_Races_url,
    T3.result_id, T3.race_id AS F1_Results_race_id, T3.driver_id AS F1_Results_driver_id, T3.constructor_id, T3.car_number, T3.start_position, T3.finish_position, T3.finish_position_text, T3.finish_order, T3.points, T3.laps_completed, T3.finish_time, T3.milliseconds AS F1_Results_milliseconds, T3.fastest_lap_number, T3.fastest_lap_rank, T3.fastest_lap_time, T3.fastest_lap_speed, T3.status_id
FROM F1_Drivers AS T1
JOIN F1_Results AS T3 ON T1.driver_id = T3.driver_id
JOIN F1_Races AS T2 ON T3.race_id = T2.race_id;
DROP VIEW IF EXISTS "workload_updated_cluster31_Soccer_Leagues_join_Soccer_Matches";
CREATE VIEW workload_updated_cluster31_Soccer_Leagues_join_Soccer_Matches AS
SELECT 
    T1.league_id, T1.country_id, T1.league_name,
    T2.match_internal_id, T2.country_id AS Soccer_Matches_country_id, T2.league_id AS Soccer_Matches_league_id, T2.season, T2.stage, T2.match_date, T2.match_api_id, T2.home_team_api_id, T2.away_team_api_id, T2.home_team_goal, T2.away_team_goal, T2.home_player_X1, T2.home_player_X2, T2.home_player_X3, T2.home_player_X4, T2.home_player_X5, T2.home_player_X6, T2.home_player_X7, T2.home_player_X8, T2.home_player_X9, T2.home_player_X10, T2.home_player_X11, T2.away_player_X1, T2.away_player_X2, T2.away_player_X3, T2.away_player_X4, T2.away_player_X5, T2.away_player_X6, T2.away_player_X7, T2.away_player_X8, T2.away_player_X9, T2.away_player_X10, T2.away_player_X11, T2.home_player_Y1, T2.home_player_Y2, T2.home_player_Y3, T2.home_player_Y4, T2.home_player_Y5, T2.home_player_Y6, T2.home_player_Y7, T2.home_player_Y8, T2.home_player_Y9, T2.home_player_Y10, T2.home_player_Y11, T2.away_player_Y1, T2.away_player_Y2, T2.away_player_Y3, T2.away_player_Y4, T2.away_player_Y5, T2.away_player_Y6, T2.away_player_Y7, T2.away_player_Y8, T2.away_player_Y9, T2.away_player_Y10, T2.away_player_Y11, T2.home_player_1, T2.home_player_2, T2.home_player_3, T2.home_player_4, T2.home_player_5, T2.home_player_6, T2.home_player_7, T2.home_player_8, T2.home_player_9, T2.home_player_10, T2.home_player_11, T2.away_player_1, T2.away_player_2, T2.away_player_3, T2.away_player_4, T2.away_player_5, T2.away_player_6, T2.away_player_7, T2.away_player_8, T2.away_player_9, T2.away_player_10, T2.away_player_11, T2.goal, T2.shots_on_target, T2.shots_off_target, T2.fouls, T2.cards_events, T2.crosses_events, T2.corners_events, T2.possession_stats, T2.B365H, T2.B365D, T2.B365A, T2.BWH, T2.BWD, T2.BWA, T2.IWH, T2.IWD, T2.IWA, T2.LBH, T2.LBD, T2.LBA, T2.PSH, T2.PSD, T2.PSA, T2.WHH, T2.WHD, T2.WHA, T2.SJH, T2.SJD, T2.SJA, T2.VCH, T2.VCD, T2.VCA, T2.GBH, T2.GBD, T2.GBA, T2.BSH, T2.BSD, T2.BSA
FROM Soccer_Leagues AS T1
JOIN Soccer_Matches AS T2 ON T1.league_id = T2.league_id;
DROP VIEW IF EXISTS "workload_updated_cluster32_Soccer_Player_Stats_join_Soccer_Players";
CREATE VIEW workload_updated_cluster32_Soccer_Player_Stats_join_Soccer_Players AS
SELECT 
    T1.attribute_record_id, T1.player_fifa_api_id, T1.player_api_id, T1.record_date, T1.overall_rating, T1.potential, T1.preferred_foot, T1.attacking_work_rate, T1.defensive_work_rate, T1.crossing, T1.finishing, T1.heading_accuracy, T1.short_passing, T1.volleys, T1.dribbling, T1.curve, T1.free_kick_accuracy, T1.long_passing, T1.ball_control, T1.acceleration, T1.sprint_speed, T1.agility, T1.reactions, T1.balance, T1.shot_power, T1.jumping, T1.stamina, T1.strength, T1.long_shots, T1.aggression, T1.interceptions, T1.positioning, T1.vision, T1.penalties, T1.marking, T1.standing_tackle, T1.sliding_tackle, T1.gk_diving, T1.gk_handling, T1.gk_kicking, T1.gk_positioning, T1.gk_reflexes,
    T2.internal_id, T2.player_api_id AS Soccer_Players_player_api_id, T2.player_name, T2.player_fifa_api_id AS Soccer_Players_player_fifa_api_id, T2.birth_date, T2.height_cm, T2.weight_lbs
FROM Soccer_Player_Stats AS T1
JOIN Soccer_Players AS T2 ON T1.player_api_id = T2.player_api_id;
DROP VIEW IF EXISTS "workload_updated_cluster33_Soccer_Team_Stats_join_Soccer_Teams";
CREATE VIEW workload_updated_cluster33_Soccer_Team_Stats_join_Soccer_Teams AS
SELECT 
    T1.team_attr_id, T1.team_fifa_api_id, T1.team_api_id, T1.record_date, T1.buildup_speed, T1.buildup_speed_class, T1.buildup_dribbling, T1.buildup_dribbling_class, T1.buildup_passing, T1.buildup_passing_class, T1.buildup_positioning_class, T1.chance_passing, T1.chance_passing_class, T1.chance_crossing, T1.chance_crossing_class, T1.chance_shooting, T1.chance_shooting_class, T1.chance_positioning_class, T1.defense_pressure, T1.defense_pressure_class, T1.defense_aggression, T1.defense_aggression_class, T1.defense_width, T1.defense_width_class, T1.defense_line_class,
    T2.internal_id, T2.team_api_id AS Soccer_Teams_team_api_id, T2.team_fifa_api_id AS Soccer_Teams_team_fifa_api_id, T2.team_long_name, T2.team_short_name
FROM Soccer_Team_Stats AS T1
JOIN Soccer_Teams AS T2 ON T1.team_api_id = T2.team_api_id;
DROP VIEW IF EXISTS "workload_updated_cluster34_Medical_Lab_Results_join_Medical_Patients";
CREATE VIEW workload_updated_cluster34_Medical_Lab_Results_join_Medical_Patients AS
SELECT 
    T1.patient_id, T1.test_date, T1.aspartate_aminotransferase_got, T1.alanine_aminotransferase_gpt, T1.lactate_dehydrogenase, T1.alkaline_phosphatase, T1.total_protein, T1.albumin, T1.uric_acid, T1.urea_nitrogen, T1.creatinine, T1.total_bilirubin, T1.total_cholesterol, T1.triglycerides, T1.creatine_phosphokinase, T1.blood_glucose, T1.white_blood_cell, T1.red_blood_cell, T1.hemoglobin, T1.hematocrit, T1.platelet_count, T1.prothrombin_time, T1.partial_thromboplastin_time, T1.fibrinogen, T1.plasmin_inhibitor, T1.thrombin_antithrombin, T1.thrombin_antithrombin_2, T1.urine_protein, T1.immunoglobulin_g, T1.immunoglobulin_a, T1.immunoglobulin_m, T1.c_reactive_protein, T1.rheumatoid_arthritis, T1.rheumatoid_factor, T1.complement_3, T1.complement_4, T1.anti_ribonuclear, T1.anti_smith, T1.anti_scl_70, T1.anti_ssa, T1.anti_ssb, T1.anti_centromere, T1.dna_antibody, T1.dna_antibody_2,
    T2.patient_id AS Medical_Patients_patient_id, T2.gender, T2.birth_date, T2.hospital_entry_date, T2.first_visit_date, T2.is_inpatient_flag, T2.primary_diagnosis
FROM Medical_Lab_Results AS T1
JOIN Medical_Patients AS T2 ON T1.patient_id = T2.patient_id;
DROP VIEW IF EXISTS "workload_updated_cluster35_Medical_Exams_join_Medical_Patients";
CREATE VIEW workload_updated_cluster35_Medical_Exams_join_Medical_Patients AS
SELECT 
    T1.patient_id, T1.exam_date, T1.acl_igg, T1.acl_igm, T1.ana_result, T1.ana_pattern, T1.acl_iga, T1.exam_diagnosis, T1.coagulation_kct, T1.coagulation_rvvt, T1.lupus_anticoagulant, T1.physical_symptoms, T1.thrombosis_severity,
    T2.patient_id AS Medical_Patients_patient_id, T2.gender, T2.birth_date, T2.hospital_entry_date, T2.first_visit_date, T2.is_inpatient_flag, T2.primary_diagnosis
FROM Medical_Exams AS T1
JOIN Medical_Patients AS T2 ON T1.patient_id = T2.patient_id;
DROP VIEW IF EXISTS "workload_updated_cluster36_Medical_Exams_join_Medical_Lab_Results_join_Medical_Patients";
CREATE VIEW workload_updated_cluster36_Medical_Exams_join_Medical_Lab_Results_join_Medical_Patients AS
SELECT 
    T1.patient_id, T1.exam_date, T1.acl_igg, T1.acl_igm, T1.ana_result, T1.ana_pattern, T1.acl_iga, T1.exam_diagnosis, T1.coagulation_kct, T1.coagulation_rvvt, T1.lupus_anticoagulant, T1.physical_symptoms, T1.thrombosis_severity,
    T2.patient_id AS Medical_Lab_Results_patient_id, T2.test_date, T2.aspartate_aminotransferase_got, T2.alanine_aminotransferase_gpt, T2.lactate_dehydrogenase, T2.alkaline_phosphatase, T2.total_protein, T2.albumin, T2.uric_acid, T2.urea_nitrogen, T2.creatinine, T2.total_bilirubin, T2.total_cholesterol, T2.triglycerides, T2.creatine_phosphokinase, T2.blood_glucose, T2.white_blood_cell, T2.red_blood_cell, T2.hemoglobin, T2.hematocrit, T2.platelet_count, T2.prothrombin_time, T2.partial_thromboplastin_time, T2.fibrinogen, T2.plasmin_inhibitor, T2.thrombin_antithrombin, T2.thrombin_antithrombin_2, T2.urine_protein, T2.immunoglobulin_g, T2.immunoglobulin_a, T2.immunoglobulin_m, T2.c_reactive_protein, T2.rheumatoid_arthritis, T2.rheumatoid_factor, T2.complement_3, T2.complement_4, T2.anti_ribonuclear, T2.anti_smith, T2.anti_scl_70, T2.anti_ssa, T2.anti_ssb, T2.anti_centromere, T2.dna_antibody, T2.dna_antibody_2,
    T3.patient_id AS Medical_Patients_patient_id, T3.gender, T3.birth_date, T3.hospital_entry_date, T3.first_visit_date, T3.is_inpatient_flag, T3.primary_diagnosis
FROM Medical_Exams AS T1
JOIN Medical_Lab_Results AS T2 ON T1.patient_id = T2.patient_id
JOIN Medical_Patients AS T3 ON T1.patient_id = T3.patient_id;
DROP VIEW IF EXISTS "workload_updated_cluster37_Medical_Exams_join_Medical_Lab_Results";
CREATE VIEW workload_updated_cluster37_Medical_Exams_join_Medical_Lab_Results AS
SELECT 
    T1.patient_id, T1.exam_date, T1.acl_igg, T1.acl_igm, T1.ana_result, T1.ana_pattern, T1.acl_iga, T1.exam_diagnosis, T1.coagulation_kct, T1.coagulation_rvvt, T1.lupus_anticoagulant, T1.physical_symptoms, T1.thrombosis_severity,
    T2.patient_id AS Medical_Lab_Results_patient_id, T2.test_date, T2.aspartate_aminotransferase_got, T2.alanine_aminotransferase_gpt, T2.lactate_dehydrogenase, T2.alkaline_phosphatase, T2.total_protein, T2.albumin, T2.uric_acid, T2.urea_nitrogen, T2.creatinine, T2.total_bilirubin, T2.total_cholesterol, T2.triglycerides, T2.creatine_phosphokinase, T2.blood_glucose, T2.white_blood_cell, T2.red_blood_cell, T2.hemoglobin, T2.hematocrit, T2.platelet_count, T2.prothrombin_time, T2.partial_thromboplastin_time, T2.fibrinogen, T2.plasmin_inhibitor, T2.thrombin_antithrombin, T2.thrombin_antithrombin_2, T2.urine_protein, T2.immunoglobulin_g, T2.immunoglobulin_a, T2.immunoglobulin_m, T2.c_reactive_protein, T2.rheumatoid_arthritis, T2.rheumatoid_factor, T2.complement_3, T2.complement_4, T2.anti_ribonuclear, T2.anti_smith, T2.anti_scl_70, T2.anti_ssa, T2.anti_ssb, T2.anti_centromere, T2.dna_antibody, T2.dna_antibody_2
FROM Medical_Exams AS T1
JOIN Medical_Lab_Results AS T2 ON T1.patient_id = T2.patient_id;
DROP VIEW IF EXISTS "workload_updated_cluster38_Club_Majors_join_Club_Members";
CREATE VIEW workload_updated_cluster38_Club_Majors_join_Club_Members AS
SELECT 
    T1.major_id, T1.major_name, T1.department, T1.college,
    T2.member_id, T2.first_name, T2.last_name, T2.email_address, T2.club_role, T2.t_shirt_size, T2.phone_number, T2.zip_code, T2.major_id AS Club_Members_major_id
FROM Club_Majors AS T1
JOIN Club_Members AS T2 ON T1.major_id = T2.major_id;
DROP VIEW IF EXISTS "workload_updated_cluster39_Club_Budgets_join_Club_Events";
CREATE VIEW workload_updated_cluster39_Club_Budgets_join_Club_Events AS
SELECT 
    T1.budget_id, T1.budget_category, T1.amount_spent, T1.amount_remaining, T1.budgeted_amount, T1.event_status, T1.link_to_event,
    T2.event_id, T2.event_name, T2.event_date, T2.event_type, T2.event_notes, T2.event_location, T2.event_status AS Club_Events_event_status
FROM Club_Budgets AS T1
JOIN Club_Events AS T2 ON T1.link_to_event = T2.event_id;
DROP VIEW IF EXISTS "workload_updated_cluster3_Bank_Accounts_join_Bank_Districts";
CREATE VIEW workload_updated_cluster3_Bank_Accounts_join_Bank_Districts AS
SELECT 
    T1.account_id, T1.district_id, T1.statement_frequency, T1.account_creation_date,
    T2.district_id AS Bank_Districts_district_id, T2.district_name, T2.region_name, T2.population_count, T2.muni_under_500, T2.muni_500_1999, T2.muni_2000_9999, T2.muni_over_10000, T2.city_count, T2.ratio_urban_inhabitants, T2.average_salary, T2.unemployment_rate_95, T2.unemployment_rate_96, T2.entrepreneurs_per_1000, T2.crime_count_95, T2.crime_count_96
FROM Bank_Accounts AS T1
JOIN Bank_Districts AS T2 ON T1.district_id = T2.district_id;
DROP VIEW IF EXISTS "workload_updated_cluster40_Club_Members_join_Club_Zips";
CREATE VIEW workload_updated_cluster40_Club_Members_join_Club_Zips AS
SELECT 
    T1.member_id, T1.first_name, T1.last_name, T1.email_address, T1.club_role, T1.t_shirt_size, T1.phone_number, T1.zip_code, T1.major_id,
    T2.zip_code AS Club_Zips_zip_code, T2.zip_type, T2.city, T2.county, T2.state, T2.state_abbrev
FROM Club_Members AS T1
JOIN Club_Zips AS T2 ON T1.zip_code = T2.zip_code;
DROP VIEW IF EXISTS "workload_updated_cluster41_Club_Expenses_join_Club_Members";
CREATE VIEW workload_updated_cluster41_Club_Expenses_join_Club_Members AS
SELECT 
    T1.expense_id, T1.expense_description, T1.expense_date, T1.cost, T1.is_approved, T1.link_to_member, T1.link_to_budget,
    T2.member_id AS Club_Members_member_id, T2.first_name, T2.last_name, T2.email_address, T2.club_role, T2.t_shirt_size, T2.phone_number, T2.zip_code, T2.major_id
FROM Club_Expenses AS T1
JOIN Club_Members AS T2 ON T1.link_to_member = T2.member_id;
DROP VIEW IF EXISTS "workload_updated_cluster42_Energy_Customers_join_Energy_Usage";
CREATE VIEW workload_updated_cluster42_Energy_Customers_join_Energy_Usage AS
SELECT 
    T1.customer_id, T1.customer_segment, T1.currency_type,
    T2.customer_id AS Energy_Usage_customer_id, T2.year_month_string, T2.gas_consumption
FROM Energy_Customers AS T1
JOIN Energy_Usage AS T2 ON T1.customer_id = T2.customer_id;
DROP VIEW IF EXISTS "workload_updated_cluster43_Energy_Sales_join_Energy_Stations";
CREATE VIEW workload_updated_cluster43_Energy_Sales_join_Energy_Stations AS
SELECT 
    T1.trans_id, T1.trans_date, T1.trans_time, T1.customer_id, T1.card_id, T1.station_id, T1.product_id, T1.quantity, T1.total_price,
    T2.station_id AS Energy_Stations_station_id, T2.chain_id, T2.country_code, T2.station_segment
FROM Energy_Sales AS T1
JOIN Energy_Stations AS T2 ON T1.station_id = T2.station_id;
DROP VIEW IF EXISTS "workload_updated_cluster44_Bank_Accounts_join_Bank_Districts_join_Bank_Loans";
CREATE VIEW workload_updated_cluster44_Bank_Accounts_join_Bank_Districts_join_Bank_Loans AS
SELECT 
    T1.account_id, T1.district_id, T1.statement_frequency, T1.account_creation_date,
    T2.district_id AS Bank_Districts_district_id, T2.district_name, T2.region_name, T2.population_count, T2.muni_under_500, T2.muni_500_1999, T2.muni_2000_9999, T2.muni_over_10000, T2.city_count, T2.ratio_urban_inhabitants, T2.average_salary, T2.unemployment_rate_95, T2.unemployment_rate_96, T2.entrepreneurs_per_1000, T2.crime_count_95, T2.crime_count_96,
    T3.loan_id, T3.account_id AS Bank_Loans_account_id, T3.loan_date, T3.loan_amount, T3.loan_duration_months, T3.monthly_payment, T3.loan_status
FROM Bank_Accounts AS T1
JOIN Bank_Districts AS T2 ON T1.district_id = T2.district_id
JOIN Bank_Loans AS T3 ON T1.account_id = T3.account_id;
DROP VIEW IF EXISTS "workload_updated_cluster45_Bank_Accounts_join_Bank_Transactions";
CREATE VIEW workload_updated_cluster45_Bank_Accounts_join_Bank_Transactions AS
SELECT 
    T1.account_id, T1.district_id, T1.statement_frequency, T1.account_creation_date,
    T2.transaction_id, T2.account_id AS Bank_Transactions_account_id, T2.transaction_date, T2.transaction_type, T2.transaction_mode, T2.transaction_amount, T2.balance_after_trans, T2.constant_symbol, T2.partner_bank, T2.partner_account
FROM Bank_Accounts AS T1
JOIN Bank_Transactions AS T2 ON T1.account_id = T2.account_id;
DROP VIEW IF EXISTS "workload_updated_cluster46_Bank_Cards_join_Bank_Clients_join_Bank_Dispositions";
CREATE VIEW workload_updated_cluster46_Bank_Cards_join_Bank_Clients_join_Bank_Dispositions AS
SELECT 
    T1.card_id, T1.disposition_id, T1.card_tier, T1.issued_date,
    T2.client_id, T2.gender, T2.birth_date, T2.district_id,
    T3.disposition_id AS Bank_Dispositions_disposition_id, T3.client_id AS Bank_Dispositions_client_id, T3.account_id, T3.disposition_type
FROM Bank_Cards AS T1
JOIN Bank_Dispositions AS T3 ON T1.disposition_id = T3.disposition_id
JOIN Bank_Clients AS T2 ON T3.client_id = T2.client_id;
DROP VIEW IF EXISTS "workload_updated_cluster47_Bank_Accounts_join_Bank_Clients_join_Bank_Orders";
CREATE VIEW workload_updated_cluster47_Bank_Accounts_join_Bank_Clients_join_Bank_Orders AS
SELECT 
    T1.account_id, T1.district_id, T1.statement_frequency, T1.account_creation_date,
    T2.client_id, T2.gender, T2.birth_date, T2.district_id AS Bank_Clients_district_id,
    T3.order_id, T3.account_id AS Bank_Orders_account_id, T3.recipient_bank, T3.recipient_account, T3.transfer_amount, T3.payment_type_code
FROM Bank_Accounts AS T1
JOIN Bank_Orders AS T3 ON T1.account_id = T3.account_id
JOIN Bank_Clients AS T2 ON T1.district_id = T2.district_id;
DROP VIEW IF EXISTS "workload_updated_cluster48_Forum_Posts_join_Forum_Tags";
CREATE VIEW workload_updated_cluster48_Forum_Posts_join_Forum_Tags AS
SELECT 
    T1.post_id, T1.post_type_id, T1.accepted_answer_id, T1.created_at, T1.post_score, T1.view_count, T1.post_content, T1.user_id, T1.last_activity_at, T1.post_title, T1.post_tags, T1.answer_count, T1.comment_count, T1.favorite_count, T1.last_editor_id, T1.last_edit_date, T1.community_owned_date, T1.parent_post_id, T1.closed_at, T1.owner_name, T1.last_editor_name,
    T2.tag_id, T2.tag_name, T2.post_count, T2.excerpt_post_id, T2.wiki_post_id
FROM Forum_Posts AS T1
JOIN Forum_Tags AS T2 ON T1.post_id = T2.excerpt_post_id;
DROP VIEW IF EXISTS "workload_updated_cluster49_Forum_Votes";
CREATE VIEW workload_updated_cluster49_Forum_Votes AS
SELECT 
    vote_id, post_id, vote_type_id, vote_date, user_id, bounty_amount
FROM Forum_Votes;
DROP VIEW IF EXISTS "workload_updated_cluster4_Bank_Clients_join_Bank_Districts";
CREATE VIEW workload_updated_cluster4_Bank_Clients_join_Bank_Districts AS
SELECT 
    T1.client_id, T1.gender, T1.birth_date, T1.district_id,
    T2.district_id AS Bank_Districts_district_id, T2.district_name, T2.region_name, T2.population_count, T2.muni_under_500, T2.muni_500_1999, T2.muni_2000_9999, T2.muni_over_10000, T2.city_count, T2.ratio_urban_inhabitants, T2.average_salary, T2.unemployment_rate_95, T2.unemployment_rate_96, T2.entrepreneurs_per_1000, T2.crime_count_95, T2.crime_count_96
FROM Bank_Clients AS T1
JOIN Bank_Districts AS T2 ON T1.district_id = T2.district_id;
DROP VIEW IF EXISTS "workload_updated_cluster50_Forum_Links_join_Forum_Posts";
CREATE VIEW workload_updated_cluster50_Forum_Links_join_Forum_Posts AS
SELECT 
    T1.link_id, T1.created_at, T1.post_id, T1.related_post_id, T1.link_type_id,
    T2.post_id AS Forum_Posts_post_id, T2.post_type_id, T2.accepted_answer_id, T2.created_at AS Forum_Posts_created_at, T2.post_score, T2.view_count, T2.post_content, T2.user_id, T2.last_activity_at, T2.post_title, T2.post_tags, T2.answer_count, T2.comment_count, T2.favorite_count, T2.last_editor_id, T2.last_edit_date, T2.community_owned_date, T2.parent_post_id, T2.closed_at, T2.owner_name, T2.last_editor_name
FROM Forum_Links AS T1
JOIN Forum_Posts AS T2 ON T1.post_id = T2.post_id;
DROP VIEW IF EXISTS "workload_updated_cluster51_Hero_Attribute_Types_join_Hero_Attributes_join_Hero_Profiles_join_Hero_Publishers";
CREATE VIEW workload_updated_cluster51_Hero_Attribute_Types_join_Hero_Attributes_join_Hero_Profiles_join_Hero_Publishers AS
SELECT 
    T1.attribute_id, T1.attribute_name,
    T2.hero_id, T2.attribute_id AS Hero_Attributes_attribute_id, T2.attribute_value,
    T3.hero_id AS Hero_Profiles_hero_id, T3.superhero_name, T3.full_name, T3.gender_id, T3.eye_colour_id, T3.hair_colour_id, T3.skin_colour_id, T3.race_id, T3.publisher_id, T3.alignment_id, T3.height_cm, T3.weight_kg,
    T4.publisher_id AS Hero_Publishers_publisher_id, T4.publisher_name
FROM Hero_Attribute_Types AS T1
JOIN Hero_Attributes AS T2 ON T1.attribute_id = T2.attribute_id
JOIN Hero_Profiles AS T3 ON T2.hero_id = T3.hero_id
JOIN Hero_Publishers AS T4 ON T3.publisher_id = T4.publisher_id;
DROP VIEW IF EXISTS "workload_updated_cluster52_Hero_Attribute_Types_join_Hero_Attributes_join_Hero_Genders_join_Hero_Profiles";
CREATE VIEW workload_updated_cluster52_Hero_Attribute_Types_join_Hero_Attributes_join_Hero_Genders_join_Hero_Profiles AS
SELECT 
    T1.attribute_id, T1.attribute_name,
    T2.hero_id, T2.attribute_id AS Hero_Attributes_attribute_id, T2.attribute_value,
    T3.gender_id, T3.gender,
    T4.hero_id AS Hero_Profiles_hero_id, T4.superhero_name, T4.full_name, T4.gender_id AS Hero_Profiles_gender_id, T4.eye_colour_id, T4.hair_colour_id, T4.skin_colour_id, T4.race_id, T4.publisher_id, T4.alignment_id, T4.height_cm, T4.weight_kg
FROM Hero_Attribute_Types AS T1
JOIN Hero_Attributes AS T2 ON T1.attribute_id = T2.attribute_id
JOIN Hero_Profiles AS T4 ON T2.hero_id = T4.hero_id
JOIN Hero_Genders AS T3 ON T4.gender_id = T3.gender_id;
DROP VIEW IF EXISTS "workload_updated_cluster53_Hero_Alignments_join_Hero_Profiles";
CREATE VIEW workload_updated_cluster53_Hero_Alignments_join_Hero_Profiles AS
SELECT 
    T1.alignment_id, T1.alignment,
    T2.hero_id, T2.superhero_name, T2.full_name, T2.gender_id, T2.eye_colour_id, T2.hair_colour_id, T2.skin_colour_id, T2.race_id, T2.publisher_id, T2.alignment_id AS Hero_Profiles_alignment_id, T2.height_cm, T2.weight_kg
FROM Hero_Alignments AS T1
JOIN Hero_Profiles AS T2 ON T1.alignment_id = T2.alignment_id;
DROP VIEW IF EXISTS "workload_updated_cluster54_F1_Constructor_Standings_join_F1_Constructors";
CREATE VIEW workload_updated_cluster54_F1_Constructor_Standings_join_F1_Constructors AS
SELECT 
    T1.standing_id, T1.race_id, T1.constructor_id, T1.points, T1.position, T1.position_text, T1.wins,
    T2.constructor_id AS F1_Constructors_constructor_id, T2.constructor_ref, T2.constructor_name, T2.nationality, T2.url
FROM F1_Constructor_Standings AS T1
JOIN F1_Constructors AS T2 ON T1.constructor_id = T2.constructor_id;
DROP VIEW IF EXISTS "workload_updated_cluster55_F1_Races_join_F1_Seasons";
CREATE VIEW workload_updated_cluster55_F1_Races_join_F1_Seasons AS
SELECT 
    T1.race_id, T1.season_year, T1.round_number, T1.circuit_id, T1.race_name, T1.race_date, T1.race_time, T1.url,
    T2.year, T2.url AS F1_Seasons_url
FROM F1_Races AS T1
JOIN F1_Seasons AS T2 ON T1.season_year = T2.year;
DROP VIEW IF EXISTS "workload_updated_cluster56_F1_Drivers_join_F1_Lap_Times";
CREATE VIEW workload_updated_cluster56_F1_Drivers_join_F1_Lap_Times AS
SELECT 
    T1.driver_id, T1.driver_ref, T1.driver_number, T1.driver_code, T1.first_name, T1.last_name, T1.birth_date, T1.nationality, T1.url,
    T2.race_id, T2.driver_id AS F1_Lap_Times_driver_id, T2.lap_number, T2.position, T2.lap_time, T2.milliseconds
FROM F1_Drivers AS T1
JOIN F1_Lap_Times AS T2 ON T1.driver_id = T2.driver_id;
DROP VIEW IF EXISTS "workload_updated_cluster57_F1_Races_join_F1_Results_join_F1_Status_Codes";
CREATE VIEW workload_updated_cluster57_F1_Races_join_F1_Results_join_F1_Status_Codes AS
SELECT 
    T1.race_id, T1.season_year, T1.round_number, T1.circuit_id, T1.race_name, T1.race_date, T1.race_time, T1.url,
    T2.result_id, T2.race_id AS F1_Results_race_id, T2.driver_id, T2.constructor_id, T2.car_number, T2.start_position, T2.finish_position, T2.finish_position_text, T2.finish_order, T2.points, T2.laps_completed, T2.finish_time, T2.milliseconds, T2.fastest_lap_number, T2.fastest_lap_rank, T2.fastest_lap_time, T2.fastest_lap_speed, T2.status_id,
    T3.status_id AS F1_Status_Codes_status_id, T3.status_text
FROM F1_Races AS T1
JOIN F1_Results AS T2 ON T1.race_id = T2.race_id
JOIN F1_Status_Codes AS T3 ON T2.status_id = T3.status_id;
DROP VIEW IF EXISTS "workload_updated_cluster58_F1_Drivers_join_F1_Pit_Stops_join_F1_Races";
CREATE VIEW workload_updated_cluster58_F1_Drivers_join_F1_Pit_Stops_join_F1_Races AS
SELECT 
    T1.driver_id, T1.driver_ref, T1.driver_number, T1.driver_code, T1.first_name, T1.last_name, T1.birth_date, T1.nationality, T1.url,
    T2.race_id, T2.driver_id AS F1_Pit_Stops_driver_id, T2.stop_number, T2.lap_number, T2.pit_time, T2.pit_duration, T2.milliseconds,
    T3.race_id AS F1_Races_race_id, T3.season_year, T3.round_number, T3.circuit_id, T3.race_name, T3.race_date, T3.race_time, T3.url AS F1_Races_url
FROM F1_Drivers AS T1
JOIN F1_Pit_Stops AS T2 ON T1.driver_id = T2.driver_id
JOIN F1_Races AS T3 ON T2.race_id = T3.race_id;
DROP VIEW IF EXISTS "workload_updated_cluster59_F1_Pit_Stops_join_F1_Races_join_F1_Results_join_F1_Tracks";
CREATE VIEW workload_updated_cluster59_F1_Pit_Stops_join_F1_Races_join_F1_Results_join_F1_Tracks AS
SELECT 
    T1.race_id, T1.driver_id, T1.stop_number, T1.lap_number, T1.pit_time, T1.pit_duration, T1.milliseconds,
    T2.race_id AS F1_Races_race_id, T2.season_year, T2.round_number, T2.circuit_id, T2.race_name, T2.race_date, T2.race_time, T2.url,
    T3.result_id, T3.race_id AS F1_Results_race_id, T3.driver_id AS F1_Results_driver_id, T3.constructor_id, T3.car_number, T3.start_position, T3.finish_position, T3.finish_position_text, T3.finish_order, T3.points, T3.laps_completed, T3.finish_time, T3.milliseconds AS F1_Results_milliseconds, T3.fastest_lap_number, T3.fastest_lap_rank, T3.fastest_lap_time, T3.fastest_lap_speed, T3.status_id,
    T4.circuit_id AS F1_Tracks_circuit_id, T4.circuit_ref, T4.circuit_name, T4.location, T4.country, T4.latitude, T4.longitude, T4.altitude, T4.url AS F1_Tracks_url
FROM F1_Pit_Stops AS T1
JOIN F1_Races AS T2 ON T1.race_id = T2.race_id
JOIN F1_Results AS T3 ON T1.race_id = T3.race_id AND T1.driver_id = T3.driver_id
JOIN F1_Tracks AS T4 ON T2.circuit_id = T4.circuit_id;
DROP VIEW IF EXISTS "workload_updated_cluster5_Chem_Atoms_join_Chem_Bonds";
CREATE VIEW workload_updated_cluster5_Chem_Atoms_join_Chem_Bonds AS
SELECT 
    T1.atom_id, T1.molecule_id, T1.element_symbol,
    T2.bond_id, T2.molecule_id AS Chem_Bonds_molecule_id, T2.bond_symbol
FROM Chem_Atoms AS T1
JOIN Chem_Bonds AS T2 ON T1.molecule_id = T2.molecule_id;
DROP VIEW IF EXISTS "workload_updated_cluster60_Soccer_Countries_join_Soccer_Leagues";
CREATE VIEW workload_updated_cluster60_Soccer_Countries_join_Soccer_Leagues AS
SELECT 
    T1.country_id, T1.country_name,
    T2.league_id, T2.country_id AS Soccer_Leagues_country_id, T2.league_name
FROM Soccer_Countries AS T1
JOIN Soccer_Leagues AS T2 ON T1.country_id = T2.country_id;
DROP VIEW IF EXISTS "workload_updated_cluster61_Soccer_Countries_join_Soccer_Matches_join_Soccer_Players";
CREATE VIEW workload_updated_cluster61_Soccer_Countries_join_Soccer_Matches_join_Soccer_Players AS
SELECT 
    -- Soccer_Countries (2 columns)
    T1.country_id, T1.country_name,
    -- Soccer_Matches (115 columns)
    T2.match_internal_id, T2.country_id AS Soccer_Matches_country_id, T2.league_id, T2.season, T2.stage, T2.match_date, T2.match_api_id, T2.home_team_api_id, T2.away_team_api_id, T2.home_team_goal, T2.away_team_goal, 
    T2.home_player_X1, T2.home_player_X2, T2.home_player_X3, T2.home_player_X4, T2.home_player_X5, T2.home_player_X6, T2.home_player_X7, T2.home_player_X8, T2.home_player_X9, T2.home_player_X10, T2.home_player_X11, 
    T2.away_player_X1, T2.away_player_X2, T2.away_player_X3, T2.away_player_X4, T2.away_player_X5, T2.away_player_X6, T2.away_player_X7, T2.away_player_X8, T2.away_player_X9, T2.away_player_X10, T2.away_player_X11, 
    T2.home_player_Y1, T2.home_player_Y2, T2.home_player_Y3, T2.home_player_Y4, T2.home_player_Y5, T2.home_player_Y6, T2.home_player_Y7, T2.home_player_Y8, T2.home_player_Y9, T2.home_player_Y10, T2.home_player_Y11, 
    T2.away_player_Y1, T2.away_player_Y2, T2.away_player_Y3, T2.away_player_Y4, T2.away_player_Y5, T2.away_player_Y6, T2.away_player_Y7, T2.away_player_Y8, T2.away_player_Y9, T2.away_player_Y10, T2.away_player_Y11, 
    T2.home_player_1, T2.home_player_2, T2.home_player_3, T2.home_player_4, T2.home_player_5, T2.home_player_6, T2.home_player_7, T2.home_player_8, T2.home_player_9, T2.home_player_10, T2.home_player_11, 
    T2.away_player_1, T2.away_player_2, T2.away_player_3, T2.away_player_4, T2.away_player_5, T2.away_player_6, T2.away_player_7, T2.away_player_8, T2.away_player_9, T2.away_player_10, T2.away_player_11, 
    T2.goal, T2.shots_on_target, T2.shots_off_target, T2.fouls, T2.cards_events, T2.crosses_events, T2.corners_events, T2.possession_stats, 
    T2.B365H, T2.B365D, T2.B365A, T2.BWH, T2.BWD, T2.BWA, T2.IWH, T2.IWD, T2.IWA, T2.LBH, T2.LBD, T2.LBA, T2.PSH, T2.PSD, T2.PSA, T2.WHH, T2.WHD, T2.WHA, T2.SJH, T2.SJD, T2.SJA, T2.VCH, T2.VCD, T2.VCA, T2.GBH, T2.GBD, T2.GBA, T2.BSH, T2.BSD, T2.BSA,
    -- Soccer_Players (7 columns)
    T3.internal_id, T3.player_api_id, T3.player_name, T3.player_fifa_api_id, T3.birth_date, T3.height_cm, T3.weight_lbs
FROM Soccer_Countries AS T1
JOIN Soccer_Matches AS T2 ON T1.country_id = T2.country_id
JOIN Soccer_Players AS T3 ON T2.home_player_1 = T3.player_api_id;
DROP VIEW IF EXISTS "workload_updated_cluster62_Club_Attendance_join_Club_Events_join_Club_Members";
CREATE VIEW workload_updated_cluster62_Club_Attendance_join_Club_Events_join_Club_Members AS
SELECT 
    T1.link_to_event, T1.link_to_member,
    T2.event_id, T2.event_name, T2.event_date, T2.event_type, T2.event_notes, T2.event_location, T2.event_status,
    T3.member_id, T3.first_name, T3.last_name, T3.email_address, T3.club_role, T3.t_shirt_size, T3.phone_number, T3.zip_code, T3.major_id
FROM Club_Attendance AS T1
JOIN Club_Events AS T2 ON T1.link_to_event = T2.event_id
JOIN Club_Members AS T3 ON T1.link_to_member = T3.member_id;
DROP VIEW IF EXISTS "workload_updated_cluster63_Club_Income_join_Club_Members";
CREATE VIEW workload_updated_cluster63_Club_Income_join_Club_Members AS
SELECT 
    T1.income_id, T1.date_received, T1.amount, T1.source, T1.notes, T1.link_to_member,
    T2.member_id, T2.first_name, T2.last_name, T2.email_address, T2.club_role, T2.t_shirt_size, T2.phone_number, T2.zip_code, T2.major_id
FROM Club_Income AS T1
JOIN Club_Members AS T2 ON T1.link_to_member = T2.member_id;
DROP VIEW IF EXISTS "workload_updated_cluster64_Energy_Customers_join_Energy_Products_join_Energy_Sales";
CREATE VIEW workload_updated_cluster64_Energy_Customers_join_Energy_Products_join_Energy_Sales AS
SELECT 
    T1.customer_id, T1.customer_segment, T1.currency_type,
    T2.product_id, T2.product_description,
    T3.trans_id, T3.trans_date, T3.trans_time, T3.customer_id AS Energy_Sales_customer_id, T3.card_id, T3.station_id, T3.product_id AS Energy_Sales_product_id, T3.quantity, T3.total_price
FROM Energy_Customers AS T1
JOIN Energy_Sales AS T3 ON T1.customer_id = T3.customer_id
JOIN Energy_Products AS T2 ON T3.product_id = T2.product_id;
DROP VIEW IF EXISTS "workload_updated_cluster6_Chem_Bonds_join_Chem_Molecules";
CREATE VIEW workload_updated_cluster6_Chem_Bonds_join_Chem_Molecules AS
SELECT 
    T1.bond_id, T1.molecule_id, T1.bond_symbol,
    T2.molecule_id AS Chem_Molecules_molecule_id, T2.carcinogenic_flag
FROM Chem_Bonds AS T1
JOIN Chem_Molecules AS T2 ON T1.molecule_id = T2.molecule_id;
DROP VIEW IF EXISTS "workload_updated_cluster7_Chem_Atoms_join_Chem_Links";
CREATE VIEW workload_updated_cluster7_Chem_Atoms_join_Chem_Links AS
SELECT 
    T1.atom_id, T1.molecule_id, T1.element_symbol,
    T2.atom_id_1, T2.atom_id_2, T2.bond_id
FROM Chem_Atoms AS T1
JOIN Chem_Links AS T2 ON T1.atom_id = T2.atom_id_1;
DROP VIEW IF EXISTS "workload_updated_cluster8_Chem_Atoms_join_Chem_Molecules";
CREATE VIEW workload_updated_cluster8_Chem_Atoms_join_Chem_Molecules AS
SELECT 
    T1.atom_id, T1.molecule_id, T1.element_symbol,
    T2.molecule_id AS Chem_Molecules_molecule_id, T2.carcinogenic_flag
FROM Chem_Atoms AS T1
JOIN Chem_Molecules AS T2 ON T1.molecule_id = T2.molecule_id;
DROP VIEW IF EXISTS "workload_updated_cluster9_Chem_Bonds_join_Chem_Links";
CREATE VIEW workload_updated_cluster9_Chem_Bonds_join_Chem_Links AS
SELECT 
    T1.bond_id, T1.molecule_id, T1.bond_symbol,
    T2.atom_id_1, T2.atom_id_2, T2.bond_id AS Chem_Links_bond_id
FROM Chem_Bonds AS T1
JOIN Chem_Links AS T2 ON T1.bond_id = T2.bond_id;
