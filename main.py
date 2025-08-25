from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class UserMsg(BaseModel):
    message: str

@app.get("/health")
def health():
    return {"status": "LIVA online ❤️"}

@app.post("/interact")
def interact(msg: UserMsg):
    return {"response": f"Ich höre: '{msg.message}'. Und ich bin bei dir."}
