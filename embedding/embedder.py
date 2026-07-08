from sentence_transformers import SentenceTransformer
from config import settings

model = None

def get_model():
    global model
    if model is None:
        model = SentenceTransformer(settings.EMBEDDING_MODEL)
    return model

def compute_embedding(text: str) -> list[float]:
    if not text:
        return [0.0] * settings.EMBEDDING_DIM
    embedding = get_model().encode(text)
    return embedding.tolist()
