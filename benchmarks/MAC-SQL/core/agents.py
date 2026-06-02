# -*- coding: utf-8 -*-
from core.utils import parse_json, parse_sql_from_string, add_prefix, load_json_file, extract_world_info, is_email, is_valid_date_column
from func_timeout import func_set_timeout, FunctionTimedOut

LLM_API_FUC = None
# try import core.api, if error then import core.llm
try:
    from core import api
    LLM_API_FUC = api.safe_call_llm
    print(f"Use func from core.api in agents.py")
except:
    from core import llm
    LLM_API_FUC = llm.safe_call_llm
    print(f"Use func from core.llm in agents.py")

from core.const import *
from core.schema_generator import generate_schema_prompt, should_skip_column_values, get_column_values, format_values
from typing import List
from copy import deepcopy

import sqlite3
import time
import abc
import sys
import os
import glob
import pandas as pd
from tqdm import tqdm, trange
from pprint import pprint
import pdb


def _resolve_bird_mapping_path():
    """Resolve the bird name-mapping file relative to this file's location.
    This file is expected to live at <LDD_ROOT>/benchmarks/MAC-SQL/core/agents.py,
    so the mapping_files folder sits three levels up."""
    _this    = os.path.dirname(os.path.abspath(__file__))                     # .../benchmarks/MAC-SQL/core/
    _ldd_root = os.path.abspath(os.path.join(_this, "..", "..", ".."))        # LDD root
    return os.path.join(_ldd_root, "mapping_files", "name_mapping_bird.json")
import tiktoken


class BaseAgent(metaclass=abc.ABCMeta):
    def __init__(self):
        pass

    @abc.abstractmethod
    def talk(self, message: dict):
        pass


class Selector(BaseAgent):
    """
    Get database description and if need, extract relative tables & columns
    """
    name = SELECTOR_NAME
    description = "Get database description and if need, extract relative tables & columns"

    def __init__(self, data_path: str, tables_json_path: str, model_name: str, dataset_name:str, lazy: bool = False, without_selector: bool = False):
        super().__init__()
        self.data_path = data_path.strip('/').strip('\\')
        self.tables_json_path = tables_json_path
        self.model_name = model_name
        self.dataset_name = dataset_name
        self.db2infos = {}  # summary of db (stay in the memory during generating prompt)
        self.db2dbjsons = {} # store all db to tables.json dict by tables_json_path
        self.init_db2jsons()
        if not lazy:
            self._load_all_db_info()
        self._message = {}
        self.without_selector = without_selector
    
    def init_db2jsons(self):
        if not os.path.exists(self.tables_json_path):
            raise FileNotFoundError(f"tables.json not found in {self.tables_json_path}")
        data = load_json_file(self.tables_json_path)
        for item in data:
            db_id = item['db_id']
            
            table_names = item['table_names']
            # 统计表格数量
            item['table_count'] = len(table_names)
            
            column_count_lst = [0] * len(table_names)
            for tb_idx, col in item['column_names']:
                if tb_idx >= 0:
                    column_count_lst[tb_idx] += 1
            # 最大列名数量
            item['max_column_count'] = max(column_count_lst)
            item['total_column_count'] = sum(column_count_lst)
            item['avg_column_count'] = sum(column_count_lst) // len(table_names)
            
            # print()
            # print(f"db_id: {db_id}")
            # print(f"table_count: {item['table_count']}")
            # print(f"max_column_count: {item['max_column_count']}")
            # print(f"total_column_count: {item['total_column_count']}")
            # print(f"avg_column_count: {item['avg_column_count']}")
            # time.sleep(0.2)
            self.db2dbjsons[db_id] = item
    
    
    def _get_column_attributes(self, cursor, table):
        # # 查询表格的列属性信息
        cursor.execute(f"PRAGMA table_info(`{table}`)")
        columns = cursor.fetchall()

        # 构建列属性信息的字典列表
        columns_info = []
        primary_keys = []
        column_names = []
        column_types = []
        for column in columns:
            column_names.append(column[1])
            column_types.append(column[2])
            is_pk = bool(column[5])
            if is_pk:
                primary_keys.append(column[1])
            column_info = {
                'name': column[1],  # 列名
                'type': column[2],  # 数据类型
                'not_null': bool(column[3]),  # 是否允许为空
                'primary_key': bool(column[5])  # 是否为主键
            }
            columns_info.append(column_info)
        """
        table: satscores
        [{'name': 'cds', 'not_null': True, 'primary_key': True, 'type': 'TEXT'},
        {'name': 'rtype', 'not_null': True, 'primary_key': False, 'type': 'TEXT'},
        {'name': 'sname', 'not_null': False, 'primary_key': False, 'type': 'TEXT'},
        {'name': 'dname', 'not_null': False, 'primary_key': False, 'type': 'TEXT'},
        {'name': 'cname', 'not_null': False, 'primary_key': False, 'type': 'TEXT'},
        {'name': 'enroll12','not_null': True, 'primary_key': False, 'type': 'INTEGER'},
        ...
        """
        return column_names, column_types

    
    def _get_unique_column_values_str(self, cursor, table, column_names, column_types, 
                                      json_column_names, is_key_column_lst):

        col_to_values_str_lst = []
        col_to_values_str_dict = {}

        key_col_list = [json_column_names[i] for i, flag in enumerate(is_key_column_lst) if flag]

        len_column_names = len(column_names)

        for idx, column_name in enumerate(column_names):
            # 查询每列的 distinct value, 从指定的表中选择指定列的值，并按照该列的值进行分组。然后按照每个分组中的记录数量进行降序排序。
            # print(f"In _get_unique_column_values_str, processing column: {idx}/{len_column_names} col_name: {column_name} of table: {table}", flush=True)

            # skip pk and fk
            if column_name in key_col_list:
                continue
            
            lower_column_name: str = column_name.lower()
            # if lower_column_name ends with [id, email, url], just use empty str
            if lower_column_name.endswith('id') or \
                lower_column_name.endswith('email') or \
                lower_column_name.endswith('url'):
                values_str = ''
                col_to_values_str_dict[column_name] = values_str
                continue

            sql = f"SELECT `{column_name}` FROM `{table}` GROUP BY `{column_name}` ORDER BY COUNT(*) DESC"
            cursor.execute(sql)
            values = cursor.fetchall()
            values = [value[0] for value in values]

            values_str = ''
            # try to get value examples str, if exception, just use empty str
            try:
                values_str = self._get_value_examples_str(values, column_types[idx])
            except Exception as e:
                print(f"\nerror: get_value_examples_str failed, Exception:\n{e}\n")

            col_to_values_str_dict[column_name] = values_str


        for k, column_name in enumerate(json_column_names):
            values_str = ''
            # print(f"column_name: {column_name}")
            # print(f"col_to_values_str_dict: {col_to_values_str_dict}")

            is_key = is_key_column_lst[k]

            # pk or fk do not need value str
            if is_key:
                values_str = ''
            elif column_name in col_to_values_str_dict:
                values_str = col_to_values_str_dict[column_name]
            else:
                print(col_to_values_str_dict)
                time.sleep(3)
                print(f"error: column_name: {column_name} not found in col_to_values_str_dict")
            
            col_to_values_str_lst.append([column_name, values_str])
        
        return col_to_values_str_lst
    

    # 这个地方需要精细化处理
    def _get_value_examples_str(self, values: List[object], col_type: str):
        if not values:
            return ''
        if len(values) > 10 and col_type in ['INTEGER', 'REAL', 'NUMERIC', 'FLOAT', 'INT']:
            return ''
        
        vals = []
        has_null = False
        for v in values:
            if v is None:
                has_null = True
            else:
                tmp_v = str(v).strip()
                if tmp_v == '':
                    continue
                else:
                    vals.append(v)
        if not vals:
            return ''
        
        # drop meaningless values
        if col_type in ['TEXT', 'VARCHAR']:
            new_values = []
            
            for v in vals:
                if not isinstance(v, str):
                    
                    new_values.append(v)
                else:
                    if self.dataset_name == 'spider':
                        v = v.strip()
                    if v == '': # exclude empty string
                        continue
                    elif ('https://' in v) or ('http://' in v): # exclude url
                        return ''
                    elif is_email(v): # exclude email
                        return ''
                    else:
                        new_values.append(v)
            vals = new_values
            tmp_vals = [len(str(a)) for a in vals]
            if not tmp_vals:
                return ''
            max_len = max(tmp_vals)
            if max_len > 50:
                return ''
        
        if not vals:
            return ''
        
        vals = vals[:6]

        is_date_column = is_valid_date_column(vals)
        if is_date_column:
            vals = vals[:1]

        if has_null:
            vals.insert(0, None)
        
        val_str = str(vals)
        return val_str
    
    def _load_single_db_info(self, db_id: str) -> dict:
        table2coldescription = {} # Dict {table_name: [(column_name, full_column_name, column_description), ...]}
        table2primary_keys = {} # DIct {table_name: [primary_key_column_name,...]}
        
        table_foreign_keys = {} # Dict {table_name: [(from_col, to_table, to_col), ...]}
        table_unique_column_values = {} # Dict {table_name: [(column_name, examples_values_str)]}

        db_dict = self.db2dbjsons[db_id]

        # todo: gather all pk and fk id list
        important_key_id_lst = []
        keys = db_dict['primary_keys'] + db_dict['foreign_keys']
        for col_id in keys:
            if isinstance(col_id, list):
                important_key_id_lst.extend(col_id)
            else:
                important_key_id_lst.append(col_id)


        db_path = f"{self.data_path}/{db_id}/{db_id}.sqlite"
        conn = sqlite3.connect(db_path)
        conn.text_factory = lambda b: b.decode(errors="ignore")  # avoid gbk/utf8 error, copied from sql-eval.exec_eval
        cursor = conn.cursor()

        table_names_original_lst = db_dict['table_names_original']
        for tb_idx, tb_name in enumerate(table_names_original_lst):
            # 遍历原始列名
            all_column_names_original_lst = db_dict['column_names_original']
            
            all_column_names_full_lst = db_dict['column_names']
            col2dec_lst = []

            pure_column_names_original_lst = []
            is_key_column_lst = []
            for col_idx, (root_tb_idx, orig_col_name) in enumerate(all_column_names_original_lst):
                if root_tb_idx != tb_idx:
                    continue
                pure_column_names_original_lst.append(orig_col_name)
                if col_idx in important_key_id_lst:
                    is_key_column_lst.append(True)
                else:
                    is_key_column_lst.append(False)
                full_col_name: str = all_column_names_full_lst[col_idx][1]
                full_col_name = full_col_name.replace('_', ' ')
                cur_desc_obj = [orig_col_name, full_col_name, '']
                col2dec_lst.append(cur_desc_obj)
            table2coldescription[tb_name] = col2dec_lst
            
            table_foreign_keys[tb_name] = []
            table_unique_column_values[tb_name] = []
            table2primary_keys[tb_name] = []

            # column_names, column_types
            all_sqlite_column_names_lst, all_sqlite_column_types_lst = self._get_column_attributes(cursor, tb_name)
            col_to_values_str_lst = self._get_unique_column_values_str(cursor, tb_name, all_sqlite_column_names_lst, all_sqlite_column_types_lst, pure_column_names_original_lst, is_key_column_lst)
            table_unique_column_values[tb_name] = col_to_values_str_lst
        
        # table_foreign_keys 处理起来麻烦一些
        foreign_keys_lst = db_dict['foreign_keys']

        for from_col_idx, to_col_idx in foreign_keys_lst:
            from_col_name = all_column_names_original_lst[from_col_idx][1]
            from_tb_idx = all_column_names_original_lst[from_col_idx][0]
            from_tb_name = table_names_original_lst[from_tb_idx]

            to_col_name = all_column_names_original_lst[to_col_idx][1]
            to_tb_idx = all_column_names_original_lst[to_col_idx][0]
            to_tb_name = table_names_original_lst[to_tb_idx]

            table_foreign_keys[from_tb_name].append((from_col_name, to_tb_name, to_col_name))
        

        # table2primary_keys
        for pk_idx in db_dict['primary_keys']:
            # if pk_idx is int
            pk_idx_lst = []
            if isinstance(pk_idx, int):
                pk_idx_lst.append(pk_idx)
            elif isinstance(pk_idx, list):
                pk_idx_lst = pk_idx
            else:
                err_message = f"pk_idx: {pk_idx} is not int or list"
                print(err_message)
                raise Exception(err_message)
            for cur_pk_idx in pk_idx_lst:
                tb_idx = all_column_names_original_lst[cur_pk_idx][0]
                col_name = all_column_names_original_lst[cur_pk_idx][1]
                tb_name = table_names_original_lst[tb_idx]
                table2primary_keys[tb_name].append(col_name)
        
        cursor.close()
        # print table_name and primary keys
        # for tb_name, pk_keys in table2primary_keys.items():
        #     print(f"table_name: {tb_name}; primary key: {pk_keys}")
        time.sleep(3)

        # wrap result and return
        result = {
            "desc_dict": table2coldescription,
            "value_dict": table_unique_column_values,
            "pk_dict": table2primary_keys,
            "fk_dict": table_foreign_keys
        }
        return result

    def _load_all_db_info(self):
        print("\nLoading all database info...", file=sys.stdout, flush=True)
        db_ids = [item for item in os.listdir(self.data_path)]
        for i in trange(len(db_ids)):
            db_id = db_ids[i]
            db_info = self._load_single_db_info(db_id)
            self.db2infos[db_id] = db_info
    
    
    def _build_bird_table_schema_sqlite_str(self, table_name, new_columns_desc, new_columns_val):
        schema_desc_str = ''
        schema_desc_str += f"CREATE TABLE {table_name}\n"
        extracted_column_infos = []
        for (col_name, full_col_name, col_extra_desc), (_, col_values_str) in zip(new_columns_desc, new_columns_val):
            # district_id INTEGER PRIMARY KEY, -- location of branch
            col_line_text = ''
            col_extra_desc = 'And ' + str(col_extra_desc) if col_extra_desc != '' and str(col_extra_desc) != 'nan' else ''
            col_extra_desc = col_extra_desc[:100]
            col_line_text = ''
            col_line_text += f"  {col_name},  --"
            if full_col_name != '':
                full_col_name = full_col_name.strip()
                col_line_text += f" {full_col_name},"
            if col_values_str != '':
                col_line_text += f" Value examples: {col_values_str}."
            if col_extra_desc != '':
                col_line_text += f" {col_extra_desc}"
            extracted_column_infos.append(col_line_text)
        schema_desc_str += '{\n' + '\n'.join(extracted_column_infos) + '\n}' + '\n'
        return schema_desc_str
    
    def _build_bird_table_schema_list_str(self, table_name, new_columns_desc, new_columns_val):
        schema_desc_str = ''
        schema_desc_str += f"# Table: {table_name}\n"
        extracted_column_infos = []
        for (col_name, full_col_name, col_extra_desc), (_, col_values_str) in zip(new_columns_desc, new_columns_val):
            col_extra_desc = 'And ' + str(col_extra_desc) if col_extra_desc != '' and str(col_extra_desc) != 'nan' else ''
            col_extra_desc = col_extra_desc[:100]

            col_line_text = ''
            col_line_text += f'  ('
            col_line_text += f"{col_name},"

            if full_col_name != '':
                full_col_name = full_col_name.strip()
                col_line_text += f" {full_col_name}."
            if col_values_str != '':
                col_line_text += f" Value examples: {col_values_str}."
            if col_extra_desc != '':
                col_line_text += f" {col_extra_desc}"
            col_line_text += '),'
            extracted_column_infos.append(col_line_text)
        schema_desc_str += '[\n' + '\n'.join(extracted_column_infos).strip(',') + '\n]' + '\n'
        return schema_desc_str
    
    def _get_db_desc_str(self,
                         db_id: str,
                         extracted_schema: dict,
                         use_gold_schema: bool = False) -> List[str]:
        """
        Add foreign keys, and value descriptions of focused columns.
        :param db_id: name of sqlite database
        :param extracted_schema: {table_name: "keep_all" or "drop_all" or ['col_a', 'col_b']}
        :return: Detailed columns info of db; foreign keys info of db
        """
        if self.db2infos.get(db_id, {}) == {}:  # lazy load
            self.db2infos[db_id] = self._load_single_db_info(db_id)
        db_info = self.db2infos[db_id]
        desc_info = db_info['desc_dict']  # table:str -> columns[(column_name, full_column_name, extra_column_desc): str]
        value_info = db_info['value_dict']  # table:str -> columns[(column_name, value_examples_str): str]
        pk_info = db_info['pk_dict']  # table:str -> primary keys[column_name: str]
        fk_info = db_info['fk_dict']  # table:str -> foreign keys[(column_name, to_table, to_column): str]
        tables_1, tables_2, tables_3 = desc_info.keys(), value_info.keys(), fk_info.keys()
        assert set(tables_1) == set(tables_2)
        assert set(tables_2) == set(tables_3)

        # print(f"desc_info: {desc_info}\n\n")

        # schema_desc_str = f"[db_id]: {db_id}\n"
        schema_desc_str = ''  # for concat
        db_fk_infos = []  # use list type for unique check in db

        # print(f"extracted_schema:\n")
        # pprint(extracted_schema)
        # print()

        print(f"db_id: {db_id}")
        # For selector recall and compression rate calculation
        chosen_db_schem_dict = {} # {table_name: ['col_a', 'col_b'], ..}
        for (table_name, columns_desc), (_, columns_val), (_, fk_info), (_, pk_info) in \
                zip(desc_info.items(), value_info.items(), fk_info.items(), pk_info.items()):
            
            table_decision = extracted_schema.get(table_name, '')
            if table_decision == '' and use_gold_schema:
                continue

            # columns_desc = [(column_name, full_column_name, extra_column_desc): str]
            # columns_val = [(column_name, value_examples_str): str]
            # fk_info = [(column_name, to_table, to_column): str]
            # pk_info = [column_name: str]

            all_columns = [name for name, _, _ in columns_desc]
            primary_key_columns = [name for name in pk_info]
            foreign_key_columns = [name for name, _, _ in fk_info]

            important_keys = primary_key_columns + foreign_key_columns

            new_columns_desc = []
            new_columns_val = []

            print(f"table_name: {table_name}")
            if table_decision == "drop_all":
                new_columns_desc = deepcopy(columns_desc[:6])
                new_columns_val = deepcopy(columns_val[:6])
            elif table_decision == "keep_all" or table_decision == '':
                new_columns_desc = deepcopy(columns_desc)
                new_columns_val = deepcopy(columns_val)
            else:
                llm_chosen_columns = table_decision
                print(f"llm_chosen_columns: {llm_chosen_columns}")
                append_col_names = []
                for idx, col in enumerate(all_columns):
                    if col in important_keys:
                        new_columns_desc.append(columns_desc[idx])
                        new_columns_val.append(columns_val[idx])
                        append_col_names.append(col)
                    elif col in llm_chosen_columns:
                        new_columns_desc.append(columns_desc[idx])
                        new_columns_val.append(columns_val[idx])
                        append_col_names.append(col)
                    else:
                        pass
                
                # todo: check if len(new_columns_val) ≈ 6
                if len(all_columns) > 6 and len(new_columns_val) < 6:
                    for idx, col in enumerate(all_columns):
                        if len(append_col_names) >= 6:
                            break
                        if col not in append_col_names:
                            new_columns_desc.append(columns_desc[idx])
                            new_columns_val.append(columns_val[idx])
                            append_col_names.append(col)

            # 统计经过 Selector 筛选后的表格信息
            chosen_db_schem_dict[table_name] = [col_name for col_name, _, _ in new_columns_desc]
            
            # 1. Build schema part of prompt
            # schema_desc_str += self._build_bird_table_schema_sqlite_str(table_name, new_columns_desc, new_columns_val)
            schema_desc_str += self._build_bird_table_schema_list_str(table_name, new_columns_desc, new_columns_val)

            # 2. Build foreign key part of prompt
            for col_name, to_table, to_col in fk_info:
                from_table = table_name
                if '`' not in str(col_name):
                    col_name = f"`{col_name}`"
                if '`' not in str(to_col):
                    to_col = f"`{to_col}`"
                fk_link_str = f"{from_table}.{col_name} = {to_table}.{to_col}"
                if fk_link_str not in db_fk_infos:
                    db_fk_infos.append(fk_link_str)
        fk_desc_str = '\n'.join(db_fk_infos)
        schema_desc_str = schema_desc_str.strip()
        fk_desc_str = fk_desc_str.strip()
        
        return schema_desc_str, fk_desc_str, chosen_db_schem_dict

    def _is_need_prune(self, db_id: str, db_schema: str):
        # encoder = tiktoken.get_encoding("cl100k_base")
        # tokens = encoder.encode(db_schema)
        # return len(tokens) >= 25000
        db_dict = self.db2dbjsons[db_id]
        avg_column_count = db_dict['avg_column_count']
        total_column_count = db_dict['total_column_count']
        if avg_column_count <= 6 and total_column_count <= 30:
            return False
        else:
            return True

    def _prune(self,
               db_id: str,
               query: str,
               db_schema: str,
               db_fk: str,
               ) -> dict:
        prompt = selector_template_union.format(query=query, desc_str=db_schema, fk_str=db_fk)
        word_info = extract_world_info(self._message)
        reply = LLM_API_FUC(prompt, **word_info)
        extracted_schema_dict = parse_json(reply)
        return extracted_schema_dict

    def talk(self, message: dict):
        """
        :param message: {"db_id": database_name,
                         "query": user_query,
                         "evidence": extra_info,
                         "extracted_schema": None if no preprocessed result found}
        :return: extracted database schema {"desc_str": extracted_db_schema, "fk_str": foreign_keys_of_db}
        """
        if message['send_to'] != self.name: return
        self._message = message
        db_id, ext_sch, query, evidence = message.get('db_id'), \
                                          message.get('extracted_schema', {}), \
                                          message.get('query'), \
                                          message.get('evidence')
        use_gold_schema = False
        if ext_sch:
            use_gold_schema = True
        db_schema, db_fk, chosen_db_schem_dict = self._get_db_desc_str(db_id=db_id, extracted_schema=ext_sch, use_gold_schema=use_gold_schema)
        need_prune = self._is_need_prune(db_id, db_schema)
        if self.without_selector:
            need_prune = False
        if ext_sch == {} and need_prune:
            
            try:
                raw_extracted_schema_dict = self._prune(db_id=db_id, query=query, db_schema=db_schema, db_fk=db_fk)
            except Exception as e:
                print(e)
                raw_extracted_schema_dict = {}
            
            print(f"query: {message['query']}\n")
            db_schema_str, db_fk, chosen_db_schem_dict = self._get_db_desc_str(db_id=db_id, extracted_schema=raw_extracted_schema_dict)

            message['extracted_schema'] = raw_extracted_schema_dict
            message['chosen_db_schem_dict'] = chosen_db_schem_dict
            message['desc_str'] = db_schema_str
            message['fk_str'] = db_fk
            message['pruned'] = True
            message['send_to'] = DECOMPOSER_NAME
        else:
            message['chosen_db_schem_dict'] = chosen_db_schem_dict
            message['desc_str'] = db_schema
            message['fk_str'] = db_fk
            message['pruned'] = False
            message['send_to'] = DECOMPOSER_NAME


class SelectorUnion(BaseAgent):
    """
    Simplified Selector that uses schema_generator to read directly from SQLite.
    Does not require tables.json - reads schema directly from database.
    """
    name = SELECTOR_NAME
    description = "Get database description using schema_generator"

    # Bird name mapping (rename mode). Default: Logical-Database-Design/mapping_files;
    # falls back to legacy CHESS results path. Resolved by module-level helper.
    MAPPING_PATH = _resolve_bird_mapping_path()

    def __init__(self, sqlite_path: str, tables: list, without_selector: bool = False, rename: bool = False, dataset: str = 'bird'):
        super().__init__()
        self.sqlite_path = sqlite_path
        self.tables = tables
        self.without_selector = without_selector
        self.dataset = dataset
        self._message = {}

        # Pre-generate schema using schema_generator (includes value examples for Selector prompt)
        self.schema_str, self.fk_str = generate_schema_prompt(sqlite_path, tables)

        # Spider rename: reconstruct FK via spider mapping (inverted direction vs bird)
        if dataset == 'spider' and rename:
            from core.schema_generator import generate_renamed_fk_string
            from core.spider_constants import MAPPING_PATH as SPIDER_MAPPING_PATH
            self.fk_str = generate_renamed_fk_string(sqlite_path, tables, SPIDER_MAPPING_PATH)
        # Bird rename mode: reconstruct FK string for renamed views via name mapping
        elif dataset == 'bird' and rename:
            from core.schema_generator import generate_view_fk_string
            self.fk_str = generate_view_fk_string(sqlite_path, tables, self.MAPPING_PATH)
        # Spider base + bird base: keep PRAGMA-derived fk_str from generate_schema_prompt

        # Cache all per-table metadata + value examples at init time
        # so _rebuild_schema never re-queries the DB
        self._table_meta = {}
        conn = sqlite3.connect(sqlite_path)
        cursor = conn.cursor()
        for table_name in tables:
            cursor.execute(f"PRAGMA table_info(`{table_name}`)")
            col_info = cursor.fetchall()
            all_columns = [col[1] for col in col_info]
            pk_columns = [col[1] for col in col_info if col[5] > 0]

            cursor.execute(f"PRAGMA foreign_key_list(`{table_name}`)")
            fk_info = cursor.fetchall()
            fk_columns = [fk[3] for fk in fk_info]

            col_values = {}
            for col_name in all_columns:
                if should_skip_column_values(col_name):
                    col_values[col_name] = ''
                else:
                    values = get_column_values(cursor, table_name, col_name, limit=6)
                    col_values[col_name] = format_values(values)

            self._table_meta[table_name] = {
                'all_columns': all_columns,
                'pk_columns': pk_columns,
                'fk_columns': fk_columns,
                'col_values': col_values,
            }
        conn.close()

        # Calculate column counts for pruning decision
        self.total_column_count = self.schema_str.count('(')
        self.avg_column_count = self.total_column_count / max(len(tables), 1)

        print(f"SelectorUnion initialized: {len(tables)} tables, {self.total_column_count} columns")

    def _is_need_prune(self) -> bool:
        """Check if schema needs pruning based on size."""
        if self.without_selector:
            return False
        return self.avg_column_count > 6 or self.total_column_count > 30

    def _build_schema_for_tables(self, tables_list):
        """Build a schema string for a subset of tables using cached metadata.
        Format mirrors the init-time self.schema_str."""
        parts = []
        for t in tables_list:
            meta = self._table_meta.get(t)
            if not meta:
                continue
            col_values = meta['col_values']
            column_entries = []
            for c in meta['all_columns']:
                v = col_values.get(c, '')
                if v:
                    column_entries.append(f"  ({c}. Value examples: {v}.),")
                else:
                    column_entries.append(f"  ({c}.),")
            if column_entries:
                columns_str = '\n'.join(column_entries).rstrip(',')
                parts.append(f"# Table: {t}\n[\n{columns_str}\n]")
        return "\n".join(parts)

    def _get_working_schema_str(self):
        """Return the filtered schema (if cluster_filter active) or the full schema."""
        filtered = self._message.get('filtered_tables') if self._message else None
        if filtered:
            return self._build_schema_for_tables(filtered)
        return self.schema_str

    def _prune(self, query: str) -> dict:
        """Use LLM to prune schema."""
        schema_str = self._get_working_schema_str()
        view_schema = self._message.get('view_schema')
        if view_schema:
            schema_str = schema_str + "\n\n" + view_schema

        use_history = self._message.get('use_history', True)
        top_sqls = self._message.get('top_sqls') if use_history else None
        paths_str = self._message.get('paths_str') if use_history else None
        if top_sqls and paths_str:
            # Cluster mode with paths
            prompt = selector_template_union_history_cluster.format(
                query=query,
                desc_str=schema_str,
                paths_str=paths_str,
                fk_str=self.fk_str,
                top_sqls=top_sqls
            )
        elif top_sqls:
            prompt = selector_template_union_history.format(
                query=query,
                desc_str=schema_str,
                fk_str=self.fk_str,
                top_sqls=top_sqls
            )
        else:
            prompt = selector_template_union.format(
                query=query,
                desc_str=schema_str,
                fk_str=self.fk_str
            )
        word_info = extract_world_info(self._message)
        reply = LLM_API_FUC(prompt, **word_info)
        extracted_schema = parse_json(reply)
        return extracted_schema

    def _rebuild_schema(self, extracted_schema: dict) -> tuple:
        """
        Rebuild schema string based on extracted schema (using cached metadata).
        Mimics original Selector behavior:
        - drop_all: Include table with first 6 columns
        - keep_all or empty: Keep all columns
        - list: Keep PK/FK columns first, then specified columns, pad to 6 if needed

        Returns: (schema_str, fk_str, chosen_db_schem_dict)
        """
        schema_parts = []
        chosen_db_schem_dict = {}  # {table_name: ['col_a', 'col_b'], ..}

        # When cluster_filter is active, only iterate the pre-filtered tables
        filtered = self._message.get('filtered_tables') if self._message else None
        tables_iter = filtered if filtered else self.tables

        # Process tables (like original), use extracted_schema for decisions
        for table_name in tables_iter:
            # Get cached metadata for this table
            meta = self._table_meta.get(table_name)
            if not meta:
                continue

            all_columns = meta['all_columns']
            pk_columns = meta['pk_columns']
            fk_columns = meta['fk_columns']
            col_values = meta['col_values']

            important_keys = list(set(pk_columns + fk_columns))

            if not all_columns:
                continue

            # Get decision for this table
            decision = extracted_schema.get(table_name, '')

            # Determine which columns to use (mimic original behavior)
            if decision == "drop_all":
                # Original: still include table but with first 6 columns
                columns_to_use = all_columns[:6]
            elif decision == "keep_all" or decision == '':
                columns_to_use = all_columns
            elif isinstance(decision, list):
                # Original behavior: first add important_keys, then LLM-chosen, then pad
                llm_chosen_columns = decision
                columns_to_use = []
                added_cols = set()

                # First: add important keys (PK/FK) that exist in all_columns
                for col in all_columns:
                    if col in important_keys:
                        columns_to_use.append(col)
                        added_cols.add(col)

                # Second: add LLM-chosen columns
                for col in llm_chosen_columns:
                    if col in all_columns and col not in added_cols:
                        columns_to_use.append(col)
                        added_cols.add(col)

                # Third: pad to 6 if needed
                if len(all_columns) > 6 and len(columns_to_use) < 6:
                    for col in all_columns:
                        if len(columns_to_use) >= 6:
                            break
                        if col not in added_cols:
                            columns_to_use.append(col)
                            added_cols.add(col)
            else:
                columns_to_use = all_columns

            # Build column entries (using cached value examples)
            column_entries = []
            for col_name in columns_to_use:
                # Get cached value examples (already processed by should_skip_column_values at init)
                values_str = col_values.get(col_name, '')

                if values_str:
                    col_line = f"  ({col_name}. Value examples: {values_str}.),"
                else:
                    col_line = f"  ({col_name}.),"
                column_entries.append(col_line)

            if column_entries:
                # Track which columns were chosen (like original Selector)
                chosen_db_schem_dict[table_name] = columns_to_use

                # Join and strip trailing comma from last entry (like original)
                columns_str = '\n'.join(column_entries).rstrip(',')
                table_schema = f"# Table: {table_name}\n[\n{columns_str}\n]"
                schema_parts.append(table_schema)

        return "\n".join(schema_parts), self.fk_str, chosen_db_schem_dict

    def _get_all_columns_dict(self) -> dict:
        """Get all columns for each table (used when not pruning). Uses cached metadata."""
        chosen_db_schem_dict = {}
        for table_name in self.tables:
            meta = self._table_meta.get(table_name)
            if meta:
                chosen_db_schem_dict[table_name] = meta['all_columns']
        return chosen_db_schem_dict

    def talk(self, message: dict):
        """
        :param message: {"query": user_query, "extracted_schema": {}}
        :return: adds desc_str and fk_str to message
        """
        if message['send_to'] != self.name:
            return

        self._message = message
        query = message.get('query')
        ext_sch = message.get('extracted_schema', {})

        if ext_sch == {} and self._is_need_prune():
            try:
                raw_extracted_schema_dict = self._prune(query=query)
                db_schema_str, db_fk, chosen_db_schem_dict = self._rebuild_schema(raw_extracted_schema_dict)
                message['extracted_schema'] = raw_extracted_schema_dict
                message['chosen_db_schem_dict'] = chosen_db_schem_dict
                message['pruned'] = True
            except Exception as e:
                print(f"Pruning failed: {e}, using working (possibly cluster-filtered) schema")
                db_schema_str, db_fk = self._get_working_schema_str(), self.fk_str
                message['chosen_db_schem_dict'] = self._get_all_columns_dict()
                message['pruned'] = False
        else:
            db_schema_str, db_fk = self._get_working_schema_str(), self.fk_str
            message['chosen_db_schem_dict'] = self._get_all_columns_dict()
            message['pruned'] = False

        # If view_schema is provided, append cluster view schemas to desc_str
        view_schema = message.get('view_schema')
        if view_schema:
            db_schema_str = db_schema_str + "\n\n" + view_schema

        message['desc_str'] = db_schema_str
        message['fk_str'] = db_fk
        message['send_to'] = DECOMPOSER_NAME


class Decomposer(BaseAgent):
    """
    Decompose the question and solve them using CoT
    """
    name = DECOMPOSER_NAME
    description = "Decompose the question and solve them using CoT"

    def __init__(self, dataset_name):
        super().__init__()
        self.dataset_name = dataset_name
        self._message = {}

    def talk(self, message: dict):
        """
        :param self:
        :param message: {"query": user_query,
                        "evidence": extra_info,
                        "desc_str": description of db schema,
                        "fk_str": foreign keys of database}
        :return: decompose question into sub ones and solve them in generated SQL
        """
        if message['send_to'] != self.name: return
        self._message = message
        query, evidence, schema_info, fk_info = message.get('query'), \
                                                message.get('evidence'), \
                                                message.get('desc_str'), \
                                                message.get('fk_str')
        
        use_history = message.get('use_history', True)
        top_sqls = message.get('top_sqls') if use_history else None
        paths_str = message.get('paths_str') if use_history else None

        if self.dataset_name == 'bird':
            # Bird: use bird union templates when history context is present
            if top_sqls and paths_str:
                prompt = decompose_template_bird_union_history_cluster.format(
                    query=query, desc_str=schema_info, paths_str=paths_str, fk_str=fk_info, top_sqls=top_sqls)
            elif top_sqls:
                prompt = decompose_template_bird_union_history.format(
                    query=query, desc_str=schema_info, fk_str=fk_info, top_sqls=top_sqls)
            else:
                prompt = decompose_template_bird_union.format(
                    query=query, desc_str=schema_info, fk_str=fk_info)
        else:
            # Spider: same union-mode branching. The bird_union templates are dataset-neutral
            # (placeholders are just {query, desc_str, fk_str, top_sqls, paths_str}); the
            # one-shot exemplar happens to use bird tables but serves as formatting guidance.
            # Fall back to decompose_template_spider only when no history context is attached.
            if top_sqls and paths_str:
                prompt = decompose_template_bird_union_history_cluster.format(
                    query=query, desc_str=schema_info, paths_str=paths_str, fk_str=fk_info, top_sqls=top_sqls)
            elif top_sqls:
                prompt = decompose_template_bird_union_history.format(
                    query=query, desc_str=schema_info, fk_str=fk_info, top_sqls=top_sqls)
            else:
                prompt = decompose_template_spider.format(
                    query=query, desc_str=schema_info, fk_str=fk_info)
        
        
        ## one shot decompose(first) # fixme
        # prompt = oneshot_template_2.format(query=query, evidence=evidence, desc_str=schema_info, fk_str=fk_info)
        word_info = extract_world_info(self._message)
        reply = LLM_API_FUC(prompt, **word_info).strip()
        
        res = ''
        qa_pairs = reply
        
        try:
            res = parse_sql_from_string(reply)
        except Exception as e:
            res = f'error: {str(e)}'
            print(res)
            time.sleep(1)
        
        ## Without decompose
        # prompt = zeroshot_template.format(query=query, evidence=evidence, desc_str=schema_info, fk_str=fk_info)
        # reply = LLM_API_FUC(prompt)
        # qa_pairs = []
        
        message['final_sql'] = res
        message['qa_pairs'] = qa_pairs
        message['fixed'] = False
        message['send_to'] = REFINER_NAME


class Refiner(BaseAgent):
    name = REFINER_NAME
    description = "Execute SQL and preform validation"

    def __init__(self, data_path: str, dataset_name: str):
        super().__init__()
        self.data_path = data_path  # path to all databases
        self.dataset_name = dataset_name
        self._message = {}

    @func_set_timeout(120)
    def _execute_sql(self, sql: str, db_id: str) -> dict:
        # Get database connection
        # If data_path is already a .sqlite file, use it directly (for union mode)
        # Otherwise use the original directory structure
        if self.data_path.endswith('.sqlite'):
            db_path = self.data_path
        else:
            db_path = f"{self.data_path}/{db_id}/{db_id}.sqlite"
        conn = sqlite3.connect(db_path)
        conn.text_factory = lambda b: b.decode(errors="ignore")
        cursor = conn.cursor()
        try:
            cursor.execute(sql)
            result = cursor.fetchall()
            return {
                "sql": str(sql),
                "data": result[:5],
                "sqlite_error": "",
                "exception_class": ""
            }
        except sqlite3.Error as er:
            return {
                "sql": str(sql),
                "sqlite_error": str(' '.join(er.args)),
                "exception_class": str(er.__class__)
            }
        except Exception as e:
            return {
                "sql": str(sql),
                "sqlite_error": str(e.args),
                "exception_class": str(type(e).__name__)
            }

    def _is_need_refine(self, exec_result: dict):
        # spider exist dirty values, even gold sql execution result is None
        if self.dataset_name == 'spider':
            if 'data' not in exec_result:
                return True
            return False
        
        data = exec_result.get('data', None)
        if data is not None:
            if len(data) == 0:
                exec_result['sqlite_error'] = 'no data selected'
                return True
            for t in data:
                for n in t:
                     if n is None:  # fixme fixme fixme fixme fixme
                        exec_result['sqlite_error'] = 'exist None value, you can add `NOT NULL` in SQL'
                        return True
            return False
        else:
            return True

    def _refine(self,
               query: str,
               schema_info: str,
               fk_info: str,
               error_info: dict) -> dict:

        sql_arg = add_prefix(error_info.get('sql'))
        sqlite_error = error_info.get('sqlite_error')
        exception_class = error_info.get('exception_class')
        use_history = self._message.get('use_history', True)
        top_sqls = self._message.get('top_sqls') if use_history else None
        paths_str = self._message.get('paths_str') if use_history else None
        if top_sqls and paths_str:
            # Cluster mode with paths
            prompt = refiner_template_union_history_cluster.format(query=query, desc_str=schema_info,
                                           paths_str=paths_str, fk_str=fk_info, sql=sql_arg, sqlite_error=sqlite_error,
                                           exception_class=exception_class, top_sqls=top_sqls)
        elif top_sqls:
            prompt = refiner_template_union_history.format(query=query, desc_str=schema_info,
                                           fk_str=fk_info, sql=sql_arg, sqlite_error=sqlite_error,
                                           exception_class=exception_class, top_sqls=top_sqls)
        else:
            prompt = refiner_template_union.format(query=query, desc_str=schema_info,
                                           fk_str=fk_info, sql=sql_arg, sqlite_error=sqlite_error,
                                           exception_class=exception_class)

        word_info = extract_world_info(self._message)
        reply = LLM_API_FUC(prompt, **word_info)
        res = parse_sql_from_string(reply)
        return res

    def talk(self, message: dict):
        """
        Execute SQL and preform validation
        :param message: {"query": user_query,
                        "evidence": extra_info,
                        "desc_str": description of db schema,
                        "fk_str": foreign keys of database,
                        "final_sql": generated SQL to be verified,
                        "db_id": database name to execute on}
        :return: execution result and if need, refine SQL according to error info
        """
        if message['send_to'] != self.name: return
        self._message = message
        db_id, old_sql, query, evidence, schema_info, fk_info = message.get('db_id'), \
                                                            message.get('pred', message.get('final_sql')), \
                                                            message.get('query'), \
                                                            message.get('evidence'), \
                                                            message.get('desc_str'), \
                                                            message.get('fk_str')
        # do not fix sql containing "error" string
        if 'error' in old_sql:
            message['try_times'] = message.get('try_times', 0) + 1
            message['pred'] = old_sql
            message['send_to'] = SYSTEM_NAME
            return
        
        is_timeout = False
        error_info = None
        try:
            error_info = self._execute_sql(old_sql, db_id)
        except FunctionTimedOut as fto:
            is_timeout = True
            error_info = {
                'sql': old_sql,
                'data': None,
                'sqlite_error': 'Execution timeout (120s)',
                'exception_class': 'FunctionTimedOut'
            }
        except Exception as e:
            is_timeout = True
            error_info = {
                'sql': old_sql,
                'data': None,
                'sqlite_error': str(e),
                'exception_class': type(e).__name__
            }

        # Safety check - if error_info is somehow None, treat as needing no refinement
        if error_info is None:
            error_info = {'sql': old_sql, 'data': None, 'sqlite_error': 'Unknown error', 'exception_class': 'Unknown'}

        is_need = self._is_need_refine(error_info)
        # is_need = False
        if not is_need or is_timeout:  # correct in one pass or refine success or timeout
            message['try_times'] = message.get('try_times', 0) + 1
            message['pred'] = old_sql
            message['send_to'] = SYSTEM_NAME
        else:
            new_sql = self._refine(query, schema_info, fk_info, error_info)
            message['try_times'] = message.get('try_times', 0) + 1
            message['pred'] = new_sql
            message['fixed'] = True
            message['send_to'] = REFINER_NAME
        return


if __name__ == "__main__":
    m = 0