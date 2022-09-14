import asyncio
import contextlib
from pathlib import Path
from typing import Any, Callable, cast

import httpx
from mutagen.id3 import APIC, ID3, PictureType
from mutagen.mp3 import MP3, EasyMP3
from pydantic import BaseModel, Field
from rich import print
from rich.progress import Progress


class MusicInfo(BaseModel):
    id: int
    seq: int
    releaseConditionId: int
    categories: list[str]
    title: str
    pronunciation: str
    lyricist: str
    composer: str
    arranger: str
    dancerCount: int
    selfDancerPosition: int
    assetBundleName: str = Field(alias="assetbundleName")
    liveTalkBackgroundAssetBundleName: str = Field(
        alias="liveTalkBackgroundAssetbundleName"
    )
    publishedAt: int
    liveStageId: int
    fillerSec: int


class Character(BaseModel):
    id: int
    musicId: int
    musicVocalId: int
    characterType: str
    characterId: int
    seq: int


class VocalInfo(BaseModel):
    id: int
    musicId: int
    musicVocalType: str
    seq: int
    releaseConditionId: int
    caption: str
    characters: list[Character]
    assetBundleName: str = Field(alias="assetbundleName")


class OutsideCharacter(BaseModel):
    id: int
    seq: int
    name: str


class GameCharacter(BaseModel):
    id: int
    seq: int
    resourceId: int
    firstName: str = ""
    givenName: str
    firstNameRuby: str = ""
    givenNameRuby: str
    gender: str
    height: int
    live2dHeightAdjustment: int
    figure: str
    breastSize: str
    modelName: str
    unit: str
    supportUnitType: str

    @property
    def full_name(self) -> str:
        return self.firstName + self.givenName


client: httpx.AsyncClient
musics: list[MusicInfo] = []
game_characters: dict[int, GameCharacter] = {}
outside_characters: dict[int, OutsideCharacter] = {}
vocal_map: dict[int, list[VocalInfo]] = {}


async def fetch_music(
    music: MusicInfo,
    vocals: list[VocalInfo],
    on_variant_complete: Callable[[], Any],
    on_complete: Callable[[], Any],
) -> None:
    authors_repr: str = ", ".join(
        i
        for i in {music.lyricist: 0, music.composer: 0, music.arranger: 0}
        if i and i != "-"
    )
    cover_png = None
    while cover_png is None:
        with contextlib.suppress(Exception):
            cover_png = (
                await client.get(
                    f"https://storage.sekai.best/sekai-assets/music/jacket/{music.assetBundleName}_rip/{music.assetBundleName}.png"
                )
            ).content
    print(f"[green] Got cover for {music.title}")
    for vocal in vocals:
        characters_tup = tuple(
            game_characters[c.characterId].full_name
            if c.characterType == "game_character"
            else outside_characters[c.characterId].name
            for c in vocal.characters
        )
        characters_repr = f"({', '.join(characters_tup)})" if characters_tup else ""
        music_file_name = f"{authors_repr} - {music.title} - {vocal.musicVocalType}{characters_repr}.mp3"
        for repl in "?*:<>|/\\":
            music_file_name = music_file_name.replace(repl, "_")
        oop_path = Path(f"./Download/{vocal.musicVocalType}/{music_file_name}")
        oop_path.parent.mkdir(parents=True, exist_ok=True)
        if oop_path.exists():
            print(f"[cyan] {music_file_name} already exists.")
            on_variant_complete()
            continue
        path: str = oop_path.as_posix()
        artists: list[str] = list(characters_tup)
        artists.extend(
            i
            for i in {music.lyricist: 0, music.composer: 0, music.arranger: 0}
            if i and i != "-"
        )
        dl = None
        while dl is None:
            try:
                dl = await client.get(
                    f"https://storage.sekai.best/sekai-assets/music/long/{vocal.assetBundleName}_rip/{vocal.assetBundleName}.mp3"
                )
                print(f"[green] Got {music_file_name}")
            except Exception as e:
                print(f"[red] {music_file_name} - {e!r}")
        with open(path, "wb") as f:
            f.write(dl.content)
        print(f"[cyan] Downloaded {music_file_name}")
        mp3 = EasyMP3(path)
        if mp3.tags is None:
            mp3.add_tags()
        mp3["title"] = music.title
        for t in ["lyricist", "composer", "arranger"]:
            if (d := getattr(music, t)) != "-":
                mp3[t] = d

        mp3["artist"] = artists
        mp3["performer"] = list(characters_tup)
        mp3["album"] = f"Project Sekai Soundtrack - {vocal.musicVocalType}"
        mp3.save()

        mp3 = MP3(path)  # Reopen so that we can use complex ID3 and add cover.
        cast(ID3, mp3.tags).add(
            APIC(
                mime="image/png",
                type=PictureType.COVER_FRONT,
                desc="Cover (front)",
                data=cover_png,
            )
        )
        mp3.save()

        print(f"[green] Saved {music_file_name} metadata.")
        on_variant_complete()
    print(f"[magenta] Downloaded {music.title}")
    on_complete()


async def main():
    async with httpx.AsyncClient() as c:
        global client, game_characters, outside_characters, musics, vocal_map
        client = c
        while not outside_characters:
            with contextlib.suppress(Exception):
                musics = list(
                    map(
                        MusicInfo.parse_obj,
                        (
                            await c.get(
                                "https://sekai-world.github.io/sekai-master-db-diff/musics.json"
                            )
                        ).json(),
                    )
                )
                print("[cyan]Fetched music list.")
                for v in map(
                    VocalInfo.parse_obj,
                    (
                        await c.get(
                            "https://sekai-world.github.io/sekai-master-db-diff/musicVocals.json"
                        )
                    ).json(),
                ):
                    vocal_map.setdefault(v.musicId, []).append(v)
                print("[green]Fetched vocal list.")
                game_characters = {
                    e.id: e
                    for e in map(
                        GameCharacter.parse_obj,
                        (
                            await c.get(
                                "https://sekai-world.github.io/sekai-master-db-diff/gameCharacters.json"
                            )
                        ).json(),
                    )
                }
                print("[dark_orange]Fetched game characters.")
                outside_characters = {
                    e.id: e
                    for e in map(
                        OutsideCharacter.parse_obj,
                        (
                            await c.get(
                                "https://sekai-world.github.io/sekai-master-db-diff/outsideCharacters.json"
                            )
                        ).json(),
                    )
                }
                print("[dark_orange]Fetched outside characters.")

        with Progress() as progress:

            dl_task = progress.add_task("[red]Downloading music...", total=len(musics))

            dl_variant_task = progress.add_task(
                "[red]Downloading variants...",
                total=sum(len(v) for v in vocal_map.values()),
            )

            def advance():
                progress.update(dl_task, advance=1)

            def advance_variant():
                progress.update(dl_variant_task, advance=1)

            await asyncio.gather(
                *(
                    fetch_music(music, vocal_map[music.id], advance_variant, advance)
                    for music in musics
                    if music.id in vocal_map
                )
            )


asyncio.run(main())
