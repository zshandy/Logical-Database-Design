# -*- coding: utf-8 -*-
from core.agents import Selector, SelectorUnion, Decomposer, Refiner
from core.const import MAX_ROUND, SYSTEM_NAME, SELECTOR_NAME, DECOMPOSER_NAME, REFINER_NAME

INIT_LOG__PATH_FUNC = None
LLM_API_FUC = None
try:
    from core import api
    LLM_API_FUC = api.safe_call_llm
    INIT_LOG__PATH_FUNC = api.init_log_path
    print(f"Use func from core.api in chat_manager.py")
except:
    from core import llm
    LLM_API_FUC = llm.safe_call_llm
    INIT_LOG__PATH_FUNC = llm.init_log_path
    print(f"Use func from core.llm in chat_manager.py")

import time
from pprint import pprint


class ChatManager(object):
    def __init__(self, data_path: str, tables_json_path: str, log_path: str, model_name: str, dataset_name:str, lazy: bool=False, without_selector: bool=False):
        self.data_path = data_path  # root path to database dir, including all databases
        self.tables_json_path = tables_json_path # path to table description json file
        self.log_path = log_path  # path to record important printed content during running
        self.model_name = model_name  # name of base LLM called by agent
        self.dataset_name = dataset_name
        self.ping_network()
        self.chat_group = [
            Selector(data_path=self.data_path, tables_json_path=self.tables_json_path, model_name=self.model_name, dataset_name=dataset_name, lazy=lazy, without_selector=without_selector),
            Decomposer(dataset_name=dataset_name),
            Refiner(data_path=self.data_path, dataset_name=dataset_name)
        ]
        INIT_LOG__PATH_FUNC(log_path)

    def ping_network(self):
        # check network status
        print("Checking network status...", flush=True)
        try:
            _ = LLM_API_FUC("Hello world!")
            print("Network is available", flush=True)
        except Exception as e:
            raise Exception(f"Network is not available: {e}")

    def _chat_single_round(self, message: dict):
        # we use `dict` type so value can be changed in the function
        for agent in self.chat_group:  # check each agent in the group
            if message['send_to'] == agent.name:
                agent.talk(message)

    def start(self, user_message: dict):
        # we use `dict` type so value can be changed in the function
        start_time = time.time()
        if user_message['send_to'] == SYSTEM_NAME:  # in the first round, pass message to prune
            user_message['send_to'] = SELECTOR_NAME
        for _ in range(MAX_ROUND):  # start chat in group
            self._chat_single_round(user_message)
            if user_message['send_to'] == SYSTEM_NAME:  # should terminate chat
                break
        end_time = time.time()
        exec_time = end_time - start_time
        print(f"\033[0;34mExecute {exec_time} seconds\033[0m", flush=True)


class ChatManagerUnion(object):
    """
    ChatManager for union mode - uses SelectorUnion with schema_generator.
    Reads schema directly from SQLite, no tables.json required.
    """
    def __init__(self, sqlite_path: str, tables: list, log_path: str, dataset_name: str = 'bird', without_selector: bool = False, rename: bool = False):
        self.sqlite_path = sqlite_path
        self.tables = tables
        self.log_path = log_path
        self.dataset_name = dataset_name

        # Initialize logging
        if log_path:
            INIT_LOG__PATH_FUNC(log_path)

        # Ping network
        self.ping_network()

        # Initialize agents
        self.chat_group = [
            SelectorUnion(sqlite_path=sqlite_path, tables=tables, without_selector=without_selector, rename=rename, dataset=dataset_name),
            Decomposer(dataset_name=dataset_name),
            Refiner(data_path=sqlite_path, dataset_name=dataset_name)
        ]

        print(f"ChatManagerUnion initialized with {len(tables)} tables")

    def ping_network(self):
        print("Checking network status...", flush=True)
        try:
            _ = LLM_API_FUC("Hello world!")
            print("Network is available", flush=True)
        except Exception as e:
            raise Exception(f"Network is not available: {e}")

    def _chat_single_round(self, message: dict):
        for agent in self.chat_group:
            if message['send_to'] == agent.name:
                t0 = time.time()
                agent.talk(message)
                elapsed = time.time() - t0
                print(f"\033[0;36m  {agent.name}: {elapsed:.2f}s\033[0m", flush=True)
                if self.log_path:
                    with open(self.log_path, 'a+', encoding='utf8') as log_fp:
                        print(f'\n[TIMING] {agent.name}: {elapsed:.2f}s\n', file=log_fp)

    def start(self, user_message: dict):
        start_time = time.time()
        if user_message['send_to'] == SYSTEM_NAME:
            user_message['send_to'] = SELECTOR_NAME
        for _ in range(MAX_ROUND):
            self._chat_single_round(user_message)
            if user_message['send_to'] == SYSTEM_NAME:
                break
        end_time = time.time()
        exec_time = end_time - start_time
        print(f"\033[0;34mExecute {exec_time} seconds\033[0m", flush=True)


if __name__ == "__main__":
    test_manager = ChatManager(data_path="../data/spider/database",
                               log_path="",
                               model_name='gpt-4-32k',
                               dataset_name='spider',
                               lazy=True)
    msg = {
        'db_id': 'concert_singer',
        'query': 'How many singers do we have?',
        'evidence': '',
        'extracted_schema': {},
        'ground_truth': 'SELECT count(*) FROM singer',
        'difficulty': 'easy',
        'send_to': SYSTEM_NAME
    }
    test_manager.start(msg)
    pprint(msg)
    print(msg['pred'])