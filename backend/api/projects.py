from fastapi import APIRouter, HTTPException

from ..schemas import ProjectCreate, ProjectUpdate
from ..services import projects

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _get_or_404(pid: str) -> dict:
    try:
        return projects.get(pid)
    except projects.NotFound as e:
        raise HTTPException(404, str(e))


@router.get("")
def list_projects():
    return projects.list_all()


@router.post("", status_code=201)
def create_project(body: ProjectCreate):
    return projects.create(body.name)


@router.get("/{pid}")
def get_project(pid: str):
    return _get_or_404(pid)


@router.put("/{pid}")
def update_project(pid: str, body: ProjectUpdate):
    _get_or_404(pid)
    return projects.update(pid, name=body.name, doc=body.doc)


@router.delete("/{pid}", status_code=204)
def delete_project(pid: str):
    _get_or_404(pid)
    projects.delete(pid)
