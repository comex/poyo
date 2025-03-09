from pathlib import Path
from dataclasses import dataclass
log_dir = Path('~/Documents/poyo-log').expanduser()

def get_unique_path(next_id: int, dir: Path, prefix: str, precision: int, suffix: str) -> tuple[Path, int]:
    while True:
        new_path = dir / f'{prefix}{next_id:0{precision}}{suffix}'
        try:
            f = new_path.open('xb')
        except FileExistsError:
            next_id += 1
        else:
            break
    f.close()
    return new_path, next_id
log_dir.mkdir(exist_ok=True)

BUTTONS = ['up', 'down', 'left', 'right', 'a', 'b', 'start', 'select']
@dataclass
class PadState:
    up: bool = False
    down: bool = False
    left: bool = False
    right: bool = False
    a: bool = False
    b: bool = False
    start: bool = False
    select: bool = False

    def as_list(self) -> list[str]:
        return [name for name in BUTTONS if getattr(self, name)]
