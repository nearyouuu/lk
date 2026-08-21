import os
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select
from datetime import datetime, timezone
import json

from app.core.deps import get_db, require_permission, get_current_user
from app.models.news import News, Tag
from app.models.user import User
from app.schemas.news import NewsOut, NewsDetailOut, TagOut, TagCreate

MEDIA_DIR = "media/news"
os.makedirs(MEDIA_DIR, exist_ok=True)

router = APIRouter(prefix="/news", tags=["news"])

@router.get("/tags", response_model=list[TagOut])
def list_tags(db: Session = Depends(get_db)):
    return db.scalars(select(Tag).order_by(Tag.name)).all()


@router.post("/tags", response_model=TagOut, dependencies=[Depends(require_permission("news:update"))])
def create_tag(payload: TagCreate, db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "Название тега не может быть пустым")

    existing = db.scalars(select(Tag).where(Tag.name.ilike(name))).first()
    if existing:
        raise HTTPException(400, "Такой тег уже существует")

    tag = Tag(name=name)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@router.post("/tags/{tag_id}", dependencies=[Depends(require_permission("news:update"))])
def delete_tag(tag_id: int, db: Session = Depends(get_db)):
    tag = db.get(Tag, tag_id)
    if not tag:
        raise HTTPException(404, "Тег не найден")

    db.delete(tag)
    db.commit()
    return {"status": "deleted", "id": tag_id}


@router.post("", dependencies=[Depends(require_permission("news:create"))])
def create_news(
    title: str = Form(...),
    body: str = Form(...),
    publish: bool = Form(False),
    tag_ids: str | None = Form(None),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    me=Depends(get_current_user),
):
    photo_path = None
    if file:
        ext = os.path.splitext(file.filename)[1]
        unique_name = f"{uuid.uuid4().hex}{ext}"
        photo_path = os.path.join(MEDIA_DIR, unique_name)
        with open(photo_path, "wb") as f:
            f.write(file.file.read())

    tags = []

    if tag_ids:
        try:
            ids = json.loads(tag_ids)
            if not isinstance(ids, list):
                raise ValueError
        except ValueError:
            raise HTTPException(400, "Ожидается JSON-массив ID тегов, например: [1,2,3]")
        tags = db.scalars(select(Tag).where(Tag.id.in_(ids))).all()
    else:
        tags = []



    news = News(
        title=title,
        body=body,
        author_id=me.id,
        is_published=publish,
        photo_path=photo_path,
        tags=tags,
    )

    if publish:
        news.published_at = datetime.now(timezone.utc)

    db.add(news)
    db.commit()
    db.refresh(news)
    return {"id": news.id}

@router.get("", response_model=list[NewsOut])
def list_news(only_published: bool = True, db: Session = Depends(get_db)):
    q = select(News).options(joinedload(News.author), joinedload(News.tags))
    if only_published:
        q = q.where(News.is_published == True)
    q = q.order_by(News.published_at.desc().nullslast())
    rows = db.execute(q).unique().scalars().all()
    return [
    NewsOut(
        id=n.id,
        title=n.title,
        body=n.body,
        published_at=n.published_at,
        author_name=n.author.full_name if n.author else None,
        photo_url=f"/{n.photo_path}" if n.photo_path else None,
        tags=[TagOut(id=t.id, name=t.name) for t in n.tags],
    )
    for n in rows
]


@router.get("/{news_id}", response_model=NewsDetailOut)
def get_news(news_id: int, db: Session = Depends(get_db)):
    q = select(News).options(joinedload(News.author), joinedload(News.tags)).where(News.id == news_id)
    news = db.scalars(q).first()
    if not news:
        raise HTTPException(404, "Новость не найдена")

    return NewsDetailOut(
        id=news.id,
        title=news.title,
        body=news.body,
        author_name=news.author.full_name if news.author else None,
        is_published=news.is_published,
        published_at=news.published_at,
        created_at=news.created_at,
        updated_at=news.updated_at,
        photo_url=f"/{news.photo_path}" if news.photo_path else None,
        tags=[TagOut(id=t.id, name=t.name) for t in news.tags],
    )


@router.post("/{news_id}/patch", dependencies=[Depends(require_permission("news:update"))])
def patch_news(
    news_id: int,
    title: str | None = Form(None),
    body: str | None = Form(None),
    publish: bool | None = Form(None),
    tags: str | None = Form(None),
    file: UploadFile | None = File(None),
    remove_photo: bool = Form(False),
    db: Session = Depends(get_db),
):
    news = db.get(News, news_id)
    if not news:
        raise HTTPException(404, "Новость не найдена")

    if isinstance(file, str) or (file and file.filename == ""):
        file = None

    if title:
        news.title = title
    if body:
        news.body = body
    if publish is not None:
        news.is_published = publish
        news.published_at = datetime.now(timezone.utc) if publish else None

    if tags is not None:
        try:
            tag_ids = json.loads(tags)
            if not isinstance(tag_ids, list):
                raise ValueError
        except ValueError:
            raise HTTPException(400, "Ожидается JSON-массив ID тегов, например: [1,2,3]")
        found_tags = db.scalars(select(Tag).where(Tag.id.in_(tag_ids))).all()
        news.tags = found_tags

    if file:
        if news.photo_path and os.path.exists(news.photo_path):
            os.remove(news.photo_path)
        ext = os.path.splitext(file.filename)[1]
        unique_name = f"{uuid.uuid4().hex}{ext}"
        photo_path = os.path.join(MEDIA_DIR, unique_name)
        with open(photo_path, "wb") as f:
            f.write(file.file.read())
        news.photo_path = photo_path
    elif remove_photo:
        if news.photo_path and os.path.exists(news.photo_path):
            os.remove(news.photo_path)
        news.photo_path = None

    news.updated_at = datetime.now(timezone.utc)
    db.add(news)
    db.commit()
    db.refresh(news)
    return {"id": news.id, "updated_at": news.updated_at}


@router.post("/{news_id}/delete", dependencies=[Depends(require_permission("news:delete"))])
def delete_news(news_id: int, db: Session = Depends(get_db)):
    news = db.get(News, news_id)
    if not news:
        raise HTTPException(404, "Новость не найдена")

    if news.photo_path and os.path.exists(news.photo_path):
        os.remove(news.photo_path)

    db.delete(news)
    db.commit()
    return {"status": "deleted", "id": news_id}
