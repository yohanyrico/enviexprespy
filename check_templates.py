from jinja2 import Environment, FileSystemLoader
import os

env = Environment(loader=FileSystemLoader('templates'))
for f in os.listdir('templates'):
    if f.endswith('.html'):
        try:
            env.get_template(f)
        except Exception as e:
            print(f'ERROR en {f}: {e}')
print("Listo")