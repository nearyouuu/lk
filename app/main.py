from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from app.core.audit_middleware import AuditMiddleware
from app.core.license_middleware import LicenseMiddleware
from app.routers import ping, auth, roles, users, schedules, grades, news, admin, applications
from app.routers import materials, me, study, director, admin_schedule, achievement, document_orders
from app.routers import admin_user_import
from app.routers import license as license_router
from app.routers import tests
def custom_generate_unique_id(route):
    return f"{route.tags[0]}_{route.name}" if route.tags else route.name

app = FastAPI(
    title="ЛК ДГТУ",
    version="2.8.4",
    generate_unique_id_function=custom_generate_unique_id,
)

app.mount(settings.MEDIA_URL, StaticFiles(directory=settings.MEDIA_ROOT), name="media")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "Content-Disposition",
        "X-Import-Created",
        "X-Import-Skipped",
        "X-Import-Failed",
        "X-Import-Groups-Created",
        "X-Import-Subdivisions-Created",
        "X-Import-Rooms-Created",
        "X-Import-Subjects-Created",
        "X-Import-Subject-Types-Created",
    ],
)
@app.get("/check_root")
def check_root(request: Request):
    return {"root_path": request.scope.get("root_path")}

app.add_middleware(AuditMiddleware)
app.add_middleware(
    LicenseMiddleware,
    exempt_paths=(
        "/license/fingerprint",
        "/license/status",
        "/ping",
        "/lk/license/fingerprint",
        "/lk/license/status",
        "/lk/ping",
    ),
)

app.include_router(ping.router)
app.include_router(license_router.router)
app.include_router(auth.router)
app.include_router(me.router)
app.include_router(users.router)
app.include_router(admin.router)
app.include_router(achievement.router)
app.include_router(study.router)
app.include_router(admin_schedule.router)
app.include_router(admin_user_import.router)
app.include_router(director.router)
app.include_router(document_orders.router)
app.include_router(materials.router)
app.include_router(schedules.router)
app.include_router(grades.router)
app.include_router(grades.grated_router)
app.include_router(tests.router)
app.include_router(news.router)

app.mount("/lk", app)
