from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import os

app = FastAPI()

if not os.path.exists("static"):
    os.makedirs("static")

app.mount("/", StaticFiles(directory="static", html=False), name="static")
