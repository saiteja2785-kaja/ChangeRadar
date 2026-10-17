from fastapi import FastAPI

app = FastAPI(title="ChangeRadar")


@app.get("/health")
def health():
    return {"status": "ok"}
