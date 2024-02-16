import ast
import astunparse
import requests
import httpx
import sys
import json
import os
import argparse
import logging
import re
import time
from typing import Tuple, Dict
import asyncio

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] <%(levelname)s> %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Define cache file
CACHE_FILE = "function_cache.json"

def get_token():
    try:
        url = "https://api.github.com/token"
        headers = {
            "Authorization": "token",
            "Editor-Version": "vscode/1.83.0",
            "Editor-Plugin-Version": "copilot-chat/0.8.0"
        }
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            json = response.json()
            if 'token' in json:
                return json['token']
        else:
            return {"error": f"Received {response.status_code} HTTP status code"}
    except Exception as e:
        return {"error": str(e)}

class SidFunctionTransformer(ast.NodeTransformer):
    def __init__(self):
        self.function_codes = []
        self.load_cache()
        self.token = get_token()
        self.token_time = time.time()

    def visit_Call(self, node: ast.Call) -> ast.AST:
        # Check if the function call is 'sid'
        if isinstance(node.func, ast.Name) and node.func.id == 'sid':
            if len(node.args) == 1:
                description, = node.args
                function_name = description.s.replace(' ', '_')
                description = description.s
                logging.info(f'Generating sid function at {node.lineno}:{node.col_offset} described as "{description}"')
            elif len(node.args) == 2:
                function_name, description = node.args
                function_name = function_name.s
                description = description.s
                logging.info(f'Generating sid function at {node.lineno}:{node.col_offset} named "{function_name}" described as "{description}"')
            else:
                logging.error(f'Wrong number of arguments at {node.lineno}:{node.col_offset}! Skipping.')
                return self.generic_visit(node)

            cache_key = (function_name, description)
            if cache_key in self.function_cache:
                function_code = self.function_cache[cache_key]
            else:
                function_code = asyncio.run(self.generate_function(function_name, description))
                self.function_cache[cache_key] = function_code
                self.save_cache()
            logging.info(f'Generated code:\n\n{function_code}\n')
            self.function_codes.append(function_code)
            return ast.Name(id=function_name, ctx=ast.Load())

        return self.generic_visit(node)

    async def generate_function(self, function_name: str, description: str) -> str:
        try:
            if time.time() - self.token_time > 600:
                self.token = get_token()
                self.token_time = time.time()

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.githubcopilot.com/chat/completions",
                    headers={
                        "Editor-Version":"vscode/1.83.0",
                        "Authorization": f"Bearer {self.token}",
                    },
                    json={
                        "messages":[{"role": "system", "content": f"Below is a python function with the name {function_name} that does the following: {description}. No code blocks/formatting are allowed. Assume any uncertainties."}],
                        "model":"gpt-4",
                        "temperature":0.4,
                        "role":"system",
                    },
                    timeout=130.0
                )

            if response.status_code != 200:
                return "Response 404"

            code = response.json()["choices"][0]["message"]["content"]
            code_blocks = re.search(r'```.*?\n(.*?)```', code, re.DOTALL)
            code = code_blocks.group(1) if code_blocks else code
            compile(code, '<string>', 'exec')
            return code
        except Exception as e:
            logging.error(f"Failed to generate function: {e}")
            return ""

    def load_cache(self):
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r') as f:
                    read_cache = json.load(f)
                    self.function_cache = {eval(k): v for k, v in read_cache.items()}
            except Exception as e:
                logging.error(f"Failed to load cache: {e}")
                self.function_cache = {}
        else:
            self.function_cache = {}

    def save_cache(self):
        try:
            with open(CACHE_FILE, 'w') as f:
                save_cache = {str((fname,desc)): code for (fname,desc), code in self.function_cache.items()}
                json.dump(save_cache, f)
        except Exception as e:
            logging.error(f"Failed to save cache: {e}")

def sid_compiler(input_path: str, output_path: str):
    try:
        with open(input_path, 'r') as f:
            code = f.read()
    except Exception as e:
        logging.error(f"Failed to read input file: {e}")
        return

    module = ast.parse(code)
    transformer = SidFunctionTransformer()
    transformer.visit(module)

    new_code = '\n\n'.join(transformer.function_codes) + astunparse.unparse(module)

    try:
        with open(output_path, 'w') as f:
            f.write(new_code)
    except Exception as e:
        logging.error(f"Failed to write output file: {e}")

def interactive_mode():
    description = input("Enter a description of the function you want to generate: ")
    function_code = asyncio.run(SidFunctionTransformer().generate_function(description.replace(" ", "_"), description))
    print(f"Generated code:\n\n{function_code}\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Sid Compiler')
    parser.add_argument('input_path', type=str, nargs='?', default=None, help='Path to the input Python script')
    parser.add_argument('output_path', type=str, nargs='?', default=None, help='Path to the output file')
    args = parser.parse_args()

    if args.input_path and args.output_path:
        sid_compiler(args.input_path, args.output_path)
    else:
        interactive_mode()
