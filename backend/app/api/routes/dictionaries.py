"""Dictionary API: system-level wordlist management."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.responses import FileResponse

from app.api.deps import require_user
from app.models.user import User
from app.schemas.dictionary import DictionaryGenerateRequest, DictionaryResponse
from app.services import dictionary_service

router = APIRouter(prefix="/dictionaries", tags=["dictionaries"])


@router.get("/", response_model=list[DictionaryResponse], summary="List all dictionaries")
async def list_dicts(
    current_user: Annotated[User, Depends(require_user)],
) -> list[DictionaryResponse]:
    dicts = await dictionary_service.list_dictionaries()
    return [DictionaryResponse(**d) for d in dicts]


@router.post("/", response_model=DictionaryResponse, summary="Upload dictionary file")
async def upload_dict(
    current_user: Annotated[User, Depends(require_user)],
    file: UploadFile = File(...),
    name: str = Form(...),
    description: str | None = Form(None),
) -> DictionaryResponse:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")
    d = await dictionary_service.create_dictionary(
        name=name,
        filename=file.filename or "wordlist.txt",
        content=content,
        description=description,
    )
    return DictionaryResponse(**d)


@router.post("/generate", response_model=DictionaryResponse, summary="Generate from mask patterns")
async def generate_dict(
    body: DictionaryGenerateRequest,
    current_user: Annotated[User, Depends(require_user)],
) -> DictionaryResponse:
    d = await dictionary_service.generate_dictionary(
        name=body.name,
        masks=body.masks,
        description=body.description,
    )
    return DictionaryResponse(**d)


@router.get("/{dict_id}", response_model=DictionaryResponse, summary="Get dictionary info")
async def get_dict(
    dict_id: int,
    current_user: Annotated[User, Depends(require_user)],
) -> DictionaryResponse:
    d = await dictionary_service.get_dictionary(dict_id)
    if not d:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dictionary not found")
    return DictionaryResponse(**d)


@router.get("/{dict_id}/download", summary="Download dictionary file")
async def download_dict(
    dict_id: int,
    current_user: Annotated[User, Depends(require_user)],
):
    d = await dictionary_service.get_dictionary(dict_id)
    if not d:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dictionary not found")
    fpath = dictionary_service.get_dictionary_path(d["filename"])
    if not fpath:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return FileResponse(str(fpath), filename=d["filename"], media_type="application/octet-stream")


@router.delete("/{dict_id}", summary="Delete dictionary")
async def delete_dict(
    dict_id: int,
    current_user: Annotated[User, Depends(require_user)],
):
    ok = await dictionary_service.delete_dictionary(dict_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dictionary not found")
    return {"ok": True}
