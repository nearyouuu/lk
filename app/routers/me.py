from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from fastapi import UploadFile, File
from sqlalchemy import select
from app.core.deps import get_db, get_current_user
from app.schemas.user import MeOut, MeAdmin, MeDirector, MeTeacher, MeStudent
from app.models.role import Role, user_roles
from app.models.profile import AdminProfile, Director
from app.models.schedule import Teacher, Group
from app.models.grade import Student as StudentModel

router = APIRouter(tags=["users"])

@router.get("/me", response_model=MeOut)
def me_alias(me=Depends(get_current_user), db: Session = Depends(get_db)):
    role_names = db.scalars(
        select(Role.name)
        .join(user_roles, user_roles.c.role_id == Role.id)
        .where(user_roles.c.user_id == me.id)
    ).all()

    profiles = []

    if "administrator" in role_names:
        adm = db.scalar(select(AdminProfile).where(AdminProfile.user_id == me.id))
        profiles.append(MeAdmin(
            fullName=me.full_name, photoUrl=me.avatar_url, email=me.email,
            subject=adm.subject if adm else None
        ))

    if "director" in role_names:
        d = db.scalar(select(Director).where(Director.user_id == me.id))
        profiles.append(MeDirector(
            fullName=d.full_name if d else me.full_name,
            email=d.email if d else me.email,
            phoneNumber=d.phone if d else me.phone,
            subject=d.subject if d else None
        ))

    teacher_id = None
    if "teacher" in role_names:
        t = db.scalar(select(Teacher).where(Teacher.user_id == me.id))
        if t:
            teacher_id = t.id
        profiles.append(MeTeacher(
            fullName=t.full_name if t else me.full_name,
            email=t.email if t else me.email,
            phoneNumber=t.phone if t else me.phone,
            subject=t.subject if t else None
        ))

    student_id = None
    if "student" in role_names:
        s = db.scalar(select(StudentModel).where(StudentModel.user_id == me.id))
        group_code = None
        if s:
            student_id = s.id
            g = db.get(Group, s.group_id)
            group_code = g.code if g else None
        profiles.append(MeStudent(
            fullName=me.full_name,
            dateOfBirth=me.birth_date.isoformat() if me.birth_date else None,
            photoUrl=me.avatar_url,
            course=s.course if s else None,
            email=me.email,
            phoneNumber=me.phone,
            studyId=s.record_book if s else None,
            group=group_code,
            insertYear=s.insert_year if s else None
        ))

    return MeOut(
        id=me.id,
        roles=role_names,
        student_id=student_id,
        teacher_id=teacher_id, 
        profiles=profiles
    )

@router.post("/me/avatar")
def me_update_avatar(
    file: UploadFile = File(...),
    me=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.core.files import save_avatar_file, delete_file_if_local
    rel = save_avatar_file(me.id, file)

    delete_file_if_local(me.avatar_url)
    me.avatar_url = rel
    db.commit()

    from app.core.config import settings
    return {
        "user_id": me.id,
        "avatar_path": rel,
        "avatar_url": f"{settings.MEDIA_URL}/{rel}",
    }
