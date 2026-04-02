# app/config/database.py

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Equivalente a spring.datasource.url
DATABASE_URL = "mysql+pymysql://root:@localhost:3306/enviexpress_bogota"

# Equivalente a spring.jpa.show-sql=true
engine = create_engine(DATABASE_URL, echo=True)

# Equivalente a SessionFactory de Hibernate
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base para todos los modelos (usado en cada model con class X(Base))
Base = declarative_base()


# Dependency para FastAPI (equivalente a @Autowired en controllers)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()