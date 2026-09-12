"""AXON memory system tests."""

import pytest
from axon.memory import MemoryStore, Memory, MemoryCategory
from axon.events import EventBus
from axon.core import Axon
from axon.security import Permission


@pytest.fixture
def memory_store():
    """Create an in-memory MemoryStore for testing."""
    bus = EventBus()
    store = MemoryStore(db_path=":memory:", event_bus=bus)
    return store, bus


# --- Store ---

def test_store_memory(memory_store):
    store, bus = memory_store
    mem = store.store("User prefers dark mode", category="preference")
    assert mem.id is not None
    assert mem.content == "User prefers dark mode"
    assert mem.category == MemoryCategory.PREFERENCE


def test_store_empty_content_raises(memory_store):
    store, _ = memory_store
    with pytest.raises(ValueError):
        store.store("")
    with pytest.raises(ValueError):
        store.store("   ")


# --- Get ---

def test_get_memory(memory_store):
    store, _ = memory_store
    created = store.store("Project root is C:/Users/Axon", category="context")
    fetched = store.get(created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.content == created.content
    assert fetched.category == MemoryCategory.CONTEXT


def test_get_invalid_id(memory_store):
    store, _ = memory_store
    assert store.get("nonexistent_id") is None
    assert store.get("") is None


# --- Search ---

def test_search_memory(memory_store):
    store, _ = memory_store
    store.store("User likes Python and Rust", category="preference")
    store.store("Project uses SQLite database", category="fact")
    store.store("Deploy script is in /scripts", category="task")

    results = store.search("Python")
    assert len(results) == 1
    assert "Python" in results[0].content

    # Case insensitive check / partial match
    results_db = store.search("database")
    assert len(results_db) == 1
    assert results_db[0].content == "Project uses SQLite database"


def test_search_empty_returns_empty(memory_store):
    store, _ = memory_store
    store.store("Something to find")
    assert store.search("") == []
    assert store.search("   ") == []


def test_search_with_category_filter(memory_store):
    store, _ = memory_store
    store.store("Favorite editor is VS Code", category="preference")
    store.store("VS Code is installed", category="fact")

    pref_results = store.search("VS Code", category="preference")
    assert len(pref_results) == 1
    assert pref_results[0].category == MemoryCategory.PREFERENCE

    fact_results = store.search("VS Code", category=MemoryCategory.FACT)
    assert len(fact_results) == 1
    assert fact_results[0].category == MemoryCategory.FACT


# --- List & Category Filtering ---

def test_list_memories_and_empty_db(memory_store):
    store, _ = memory_store
    # Empty DB
    assert store.list() == []

    store.store("Fact 1", category="fact")
    store.store("Pref 1", category="preference")
    store.store("Fact 2", category="fact")

    all_mems = store.list()
    assert len(all_mems) == 3

    facts = store.list(category="fact")
    assert len(facts) == 2
    assert all(m.category == MemoryCategory.FACT for m in facts)

    prefs = store.list(category=MemoryCategory.PREFERENCE)
    assert len(prefs) == 1
    assert prefs[0].content == "Pref 1"


# --- Forget ---

def test_forget_memory(memory_store):
    store, _ = memory_store
    mem = store.store("Temporary secret reminder")
    assert store.get(mem.id) is not None

    deleted = store.forget(mem.id)
    assert deleted is True
    assert store.get(mem.id) is None


def test_forget_invalid_id(memory_store):
    store, _ = memory_store
    assert store.forget("nonexistent") is False
    assert store.forget("") is False


# --- Persistence ---

def test_sqlite_persistence(tmp_path):
    db_file = str(tmp_path / "test_memory.db")
    store1 = MemoryStore(db_path=db_file)
    m1 = store1.store("Persisted memory entry", category="fact")
    store1.close()

    # Re-open the database from file
    store2 = MemoryStore(db_path=db_file)
    retrieved = store2.get(m1.id)
    assert retrieved is not None
    assert retrieved.content == "Persisted memory entry"
    assert retrieved.category == MemoryCategory.FACT
    store2.close()


# --- Events ---

def test_memory_events_emitted(memory_store):
    store, bus = memory_store
    events_log = []

    bus.on("MEMORY_CREATED", lambda e: events_log.append((e.name, e.data)))
    bus.on("MEMORY_DELETED", lambda e: events_log.append((e.name, e.data)))

    mem = store.store("Test event emission", category="task")
    assert len(events_log) == 1
    assert events_log[0][0] == "MEMORY_CREATED"
    assert events_log[0][1]["id"] == mem.id
    assert events_log[0][1]["category"] == "task"

    store.forget(mem.id)
    assert len(events_log) == 2
    assert events_log[1][0] == "MEMORY_DELETED"
    assert events_log[1][1]["id"] == mem.id


# --- Router & Tool Integration ---

def test_memory_tools_via_router(tmp_path):
    db_file = str(tmp_path / "runtime_memory.db")
    axon = Axon()
    axon.config._data["memory_db_path"] = db_file
    axon.memory = MemoryStore(db_path=db_file, event_bus=axon.events)
    axon.start()

    # memory.store tool
    res_store = axon.router.execute("memory.store", content="User loves dark themes", category="preference")
    assert res_store["success"] is True
    mem_id = res_store["result"]["id"]

    # memory.get tool
    res_get = axon.router.execute("memory.get", memory_id=mem_id)
    assert res_get["success"] is True
    assert res_get["result"]["content"] == "User loves dark themes"

    # memory.search tool
    res_search = axon.router.execute("memory.search", query="dark")
    assert res_search["success"] is True
    assert len(res_search["result"]) == 1

    # memory.list tool
    res_list = axon.router.execute("memory.list")
    assert res_list["success"] is True
    assert len(res_list["result"]) == 1

    # memory.forget requires approval
    # Without approval callback, it must fail
    res_forget_denied = axon.router.execute("memory.forget", memory_id=mem_id)
    assert res_forget_denied["success"] is False
    assert "approval denied" in res_forget_denied["error"].lower()

    # With approval callback granting permission
    axon.approval.set_prompt(lambda name, kwargs: True)
    res_forget_granted = axon.router.execute("memory.forget", memory_id=mem_id)
    assert res_forget_granted["success"] is True
    assert res_forget_granted["result"] is True

    axon.shutdown()


def test_memory_multithreaded_access(tmp_path):
    """Verify that MemoryStore can be safely read and written across threads (e.g. in web AI threads)."""
    import threading
    db_file = str(tmp_path / "thread_memory.db")
    axon = Axon()
    axon.config._data["memory_db_path"] = db_file
    axon.memory = MemoryStore(db_path=db_file, event_bus=axon.events)
    axon.start()

    errors = []
    results = []

    def worker(i):
        try:
            res = axon.router.execute("memory.store", content=f"Fact number {i}", category="fact")
            if not res.get("success"):
                errors.append(res.get("error"))
            else:
                results.append(res["result"]["id"])
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"Encountered thread errors: {errors}"
    assert len(results) == 10

    # Search and list from another thread
    search_res = []
    t_search = threading.Thread(
        target=lambda: search_res.append(axon.router.execute("memory.search", query="Fact"))
    )
    t_search.start()
    t_search.join()

    assert len(search_res) == 1
    assert search_res[0]["success"] is True
    assert len(search_res[0]["result"]) == 10

    axon.shutdown()

