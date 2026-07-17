from sqlalchemy import Column, Integer, String, ForeignKey, Text, Float, JSON
from sqlalchemy.orm import declarative_base, relationship
from pgvector.sqlalchemy import Vector

Base = declarative_base()

class Lecturer(Base):
    __tablename__ = 'lecturers'
    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True)
    lecturer_code = Column(String)
    study_program = Column(String)
    research_group = Column(String)
    academic_rank = Column(String)
    field = Column(String)
    
    full_name = Column(String)
    titles = Column(String)
    name_with_title = Column(String)
    email = Column(String)
    photo = Column(String)
    
    citation_count = Column(Integer, default=0)
    h_index = Column(Integer, default=0)
    i10_index = Column(Integer, default=0)
    
    sinta_scopus_citations = Column(Integer, default=0)
    sinta_scopus_h_index = Column(Integer, default=0)
    sinta_scopus_i10_index = Column(Integer, default=0)
    
    sinta_scholar_citations = Column(Integer, default=0)
    sinta_scholar_h_index = Column(Integer, default=0)
    sinta_scholar_i10_index = Column(Integer, default=0)
    
    sinta_wos_citations = Column(Integer, default=0)
    sinta_wos_h_index = Column(Integer, default=0)
    sinta_wos_i10_index = Column(Integer, default=0)
    
    ai_categories = Column(JSON, default=list)
    sinta_metrics = Column(JSON, default=dict)

    profiles = relationship("Profile", back_populates="lecturer")
    publications = relationship("Publication", back_populates="lecturer")
    keywords = relationship("Keyword", back_populates="lecturer")
    research_interests = relationship("ResearchInterest", back_populates="lecturer")
    coauthors = relationship("Coauthor", back_populates="lecturer")
    embeddings = relationship("Embedding", back_populates="lecturer", uselist=False)

class Profile(Base):
    __tablename__ = 'profiles'
    id = Column(Integer, primary_key=True)
    lecturer_id = Column(Integer, ForeignKey('lecturers.id'))
    platform = Column(String)
    url = Column(String)
    lecturer = relationship("Lecturer", back_populates="profiles")

class Publication(Base):
    __tablename__ = 'publications'
    id = Column(Integer, primary_key=True)
    lecturer_id = Column(Integer, ForeignKey('lecturers.id'))
    title = Column(Text)
    year = Column(Integer, nullable=True)
    lecturer = relationship("Lecturer", back_populates="publications")

class Keyword(Base):
    __tablename__ = 'keywords'
    id = Column(Integer, primary_key=True)
    lecturer_id = Column(Integer, ForeignKey('lecturers.id'))
    keyword = Column(String)
    lecturer = relationship("Lecturer", back_populates="keywords")

class ResearchInterest(Base):
    __tablename__ = 'research_interests'
    id = Column(Integer, primary_key=True)
    lecturer_id = Column(Integer, ForeignKey('lecturers.id'))
    interest = Column(String)
    lecturer = relationship("Lecturer", back_populates="research_interests")

class Coauthor(Base):
    __tablename__ = 'coauthors'
    id = Column(Integer, primary_key=True)
    lecturer_id = Column(Integer, ForeignKey('lecturers.id'))
    coauthor_name = Column(String)
    lecturer = relationship("Lecturer", back_populates="coauthors")

class Embedding(Base):
    __tablename__ = 'embeddings'
    id = Column(Integer, primary_key=True)
    lecturer_id = Column(Integer, ForeignKey('lecturers.id'), unique=True)
    keyword_embedding = Column(Vector(384))
    publication_embedding = Column(Vector(384))
    lecturer = relationship("Lecturer", back_populates="embeddings")

class Recommendation(Base):
    __tablename__ = 'recommendations'
    id = Column(Integer, primary_key=True)
    lecturer_id = Column(Integer, ForeignKey('lecturers.id'))
    recommended_lecturer_id = Column(Integer, ForeignKey('lecturers.id'))
    score = Column(Float)
    reasons = Column(JSON)

class Collaboration(Base):
    __tablename__ = 'collaborations'
    id = Column(Integer, primary_key=True)
    lecturer_id_1 = Column(Integer, ForeignKey('lecturers.id'))
    lecturer_id_2 = Column(Integer, ForeignKey('lecturers.id'))
    collaboration_count = Column(Integer, default=1)
    shared_publications = Column(JSON)
