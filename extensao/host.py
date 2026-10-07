#!/usr/bin/env python3
import sys
import json
import struct
import os

# Caminho para o arquivo escolha_do_editor.txt
# Presume que este script está na pasta 'extensao' e o .txt está na raiz do projeto
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILE_PATH = os.path.join(BASE_DIR, "escolha_do_editor.txt")

def read_message():
    raw_length = sys.stdin.buffer.read(4)
    if len(raw_length) == 0:
        sys.exit(0)
    message_length = struct.unpack('@I', raw_length)[0]
    message = sys.stdin.buffer.read(message_length).decode('utf-8')
    return json.loads(message)

def send_message(message_dict):
    encoded_content = json.dumps(message_dict).encode('utf-8')
    sys.stdout.buffer.write(struct.pack('@I', len(encoded_content)))
    sys.stdout.buffer.write(encoded_content)
    sys.stdout.buffer.flush()

def main():
    while True:
        try:
            data = read_message()
            
            url = data.get('url', '').strip()
            lang = data.get('lang', '').strip()
            comment = data.get('comment', '').strip()
            
            if not url:
                send_message({"success": False, "error": "URL is empty"})
                continue
            
            # Montar a linha
            # Sintaxe: URL [| nota do editor] [| @arquivo.html] [| lang=xx]
            entry = url
            if comment:
                entry += f" | {comment}"
            if lang:
                entry += f" | lang={lang}"
                
            with open(FILE_PATH, "a", encoding="utf-8") as f:
                f.write("\n" + entry + "\n")
                
            send_message({"success": True})
            
        except Exception as e:
            send_message({"success": False, "error": str(e)})
            sys.exit(1)

if __name__ == '__main__':
    main()
