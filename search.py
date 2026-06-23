import os
import sys
import subprocess
import sqlite3
import time
from pathlib import Path
from typing import Final, Generator

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, DataTable

class Config:
    DB_NAME: Final[str] = "harmony.db"
    
    @classmethod
    def get_db_path(cls) -> Path:
        if sys.platform == "win32":
            base_dir = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local")))
        elif sys.platform == "darwin":
            base_dir = Path(os.path.expanduser("~/Library/Caches"))
        else:
            base_dir = Path(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")))
            
        app_dir = base_dir / "harmony"
        app_dir.mkdir(parents=True, exist_ok=True)
        return app_dir / cls.DB_NAME

    @classmethod
    def get_search_roots(cls) -> list[Path]:
        if sys.platform == "win32":
            import ctypes
            import string
            drives = []
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for letter in string.ascii_uppercase:
                if bitmask & 1:
                    drives.append(Path(f"{letter}:\\"))
                bitmask >>= 1
            return drives
        
        return [Path("/")]

class DatabaseManager:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = OFF;")
        conn.execute("PRAGMA mmap_size = 268435456;")
        conn.execute("PRAGMA cache_size = -64000;")
        return conn

    def _init_db(self) -> None:
        with self.get_connection() as conn:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS file_index USING fts5(
                    name,
                    path UNINDEXED,
                    tokenize="trigram"
                );
            """)
            conn.commit()

    def reset_database(self) -> None:
        with self.get_connection() as conn:
            conn.execute("DROP TABLE IF EXISTS file_index;")
            conn.commit()
        
        with self.get_connection() as conn:
            conn.execute("VACUUM;")
        self._init_db()

    def needs_reindex(self) -> bool:
        with self.get_connection() as conn:
            try:
                cursor = conn.execute("SELECT COUNT(*) FROM file_index")
                count = cursor.fetchone()[0]
                
                return count < 10000  
            except sqlite3.OperationalError:
                return True

    def bulk_insert(self, generator: Generator[tuple[str, str], None, None]) -> None:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            chunk: list[tuple[str, str]] = []
            
            for item in generator:
                chunk.append(item)
                if len(chunk) >= 50000:
                    cursor.executemany("INSERT INTO file_index (name, path) VALUES (?, ?);", chunk)
                    chunk.clear()
            if chunk:
                cursor.executemany("INSERT INTO file_index (name, path) VALUES (?, ?);", chunk)
            conn.commit()

    def search(self, query_str: str, limit: int = 150) -> list[tuple[str, str]]:
        query_str = query_str.strip()
        if not query_str:
            return []
        
        with self.get_connection() as conn:
            
            if len(query_str) < 3:
                sql = "SELECT name, path FROM file_index WHERE name LIKE ? LIMIT ?;"
                return conn.execute(sql, (f"%{query_str}%", limit)).fetchall()

            sanitized = query_str.replace('"', '""')
            sql = "SELECT name, path FROM file_index WHERE file_index MATCH ? ORDER BY rank LIMIT ?;"
            
            try:
                return conn.execute(sql, (f'"{sanitized}"', limit)).fetchall()
            except sqlite3.OperationalError:
                fallback_sql = "SELECT name, path FROM file_index WHERE name LIKE ? LIMIT ?;"
                return conn.execute(fallback_sql, (f"%{query_str}%", limit)).fetchall()

class IndexController:
    def __init__(self, db_mgr: DatabaseManager, roots: list[Path]):
        self.db_mgr = db_mgr
        self.roots = roots

    def scan_and_seed(self) -> None:
        print("\nindexer")
        print("starting full filesystem scan.")
        
        start_time = time.time()
        self.db_mgr.bulk_insert(self._discover_generator())
        elapsed = time.time() - start_time
        
        print(f"\n\nIndexing complete in {elapsed:.2f} seconds.")
        print("launching interface\n")
        time.sleep(1.5)

    def _discover_generator(self) -> Generator[tuple[str, str], None, None]:
        total_files = 0
        for root in self.roots:
            root_str = str(root)
            print(f"\nscanning drive: {root_str}")
            
            stack = [root_str]
            
            while stack:
                current_dir = stack.pop()
                try:
                    with os.scandir(current_dir) as iterator:
                        for entry in iterator:
                            try:
                                if entry.is_symlink():
                                    continue
                                    
                                if entry.is_dir():
                                    stack.append(entry.path)
                                elif entry.is_file():
                                    total_files += 1
                                    
                                    if total_files % 10000 == 0:
                                        msg = f"Indexed {total_files:,} files... [{entry.name[:25]}]"
                                        sys.stdout.write(f"\r{msg:<70}")
                                        sys.stdout.flush()
                                        
                                    yield entry.name, entry.path
                                    
                            except OSError:
                                continue
                except PermissionError:
                    continue
                except OSError:
                    continue

class EverythingTUI(App[None]):
    CSS = """
    Screen {
        background: transparent;
    }
    Vertical {
        margin: 0;
        padding: 0;
    }
    Input {
        dock: top;
        border: none;
        background: transparent;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    Input:focus {
        border: none;
    }
    
    DataTable {
        height: 1fr;
        border: none;
        background: transparent;
        scrollbar-size: 0 0; 
        overflow-x: hidden;  
    }
    
    DataTable > .datatable--cursor {
        background: red;
        color: white;
    }
    
    DataTable > .datatable--hover {
        background: darkred;
    }

    """
    
    BINDINGS = [
        ("escape", "clear_search", "Clear"),
        ("ctrl+q", "quit", "Exit"),
        ("ctrl+o", "open_folder", "Open Folder"),
        
    ]

    def __init__(self, db_mgr: DatabaseManager):
        super().__init__()
        self.db_mgr = db_mgr

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Input(placeholder="> search ", id="search_input")
            yield DataTable(id="results_table")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.show_header = False
        table.add_columns("file Name", "system storage absolute path")
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        table = self.query_one(DataTable)
        if table.row_count > 0:
            row_data = table.get_row_at(0)
            target_path = str(row_data[1])
            self._execute_file(target_path)

    def on_input_changed(self, event: Input.Changed) -> None:
        self.trigger_search(event.value)

    @work(exclusive=True, thread=True)
    def trigger_search(self, search_query: str) -> None:
        table = self.query_one(DataTable)
        if not search_query.strip():
            self.call_from_thread(table.clear)
            return

        raw_matches = self.db_mgr.search(search_query, limit=150)
        
        self.call_from_thread(table.clear)
        for name, path in raw_matches:
            self.call_from_thread(table.add_row, name, path)

    def action_clear_search(self) -> None:
        input_widget = self.query_one(Input)
        input_widget.value = ""
        self.query_one(DataTable).clear()
        input_widget.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        table = self.query_one(DataTable)
        row_data = table.get_row(event.row_key)
        target_path = str(row_data[1])
        self._execute_file(target_path)

    def _get_selected_path(self) -> str | None:
        table = self.query_one(DataTable)
        if table.cursor_coordinate is not None:
            row_index = table.cursor_coordinate.row
            row_data = table.get_row_at(row_index)
            return str(row_data[1])
        return None

    def _execute_file(self, target_path: str) -> None:
        if not target_path or not os.path.exists(target_path):
            return
            
        is_executable = os.access(target_path, os.X_OK) and not os.path.isdir(target_path)
        
        try:
            if sys.platform == "win32":
                os.startfile(target_path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", target_path])
            else:
                if is_executable:
                    subprocess.Popen([target_path], start_new_session=True)
                else:
                    subprocess.Popen(["xdg-open", target_path], start_new_session=True)
        except Exception:
            pass 

    def action_open_folder(self) -> None:
        target_file = self._get_selected_path()
        if not target_file or not os.path.exists(target_file):
            return

        parent_folder = str(Path(target_file).parent)
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", os.path.normpath(target_file)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", target_file])
            else:
                subprocess.Popen(["xdg-open", parent_folder], start_new_session=True)
        except Exception:
            pass

def main() -> None:
    db_file_path = Config.get_db_path()
    db_mgr = DatabaseManager(db_file_path)
    search_roots = Config.get_search_roots()
    
    needs_reindex = db_mgr.needs_reindex() or "--reindex" in sys.argv
    controller = IndexController(db_mgr, search_roots)
    
    if needs_reindex:
        print("empty or broken index detected.")
        db_mgr.reset_database()
        controller.scan_and_seed()
    
    tui_app = EverythingTUI(db_mgr)
    tui_app.run()

if __name__ == "__main__":
    main()