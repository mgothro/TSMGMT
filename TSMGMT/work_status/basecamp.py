from flask import current_app, url_for, redirect, session
from datetime import datetime
import pyodbc as p
import time
import re
from ratelimit import limits, sleep_and_retry
from requests.exceptions import HTTPError, SSLError
from urllib3.exceptions import ProtocolError, MaxRetryError
from authlib.integrations.flask_client import OAuth
from typing import List, Tuple, Optional
# your existing DB & util imports:
from ..db.connection import execute_query, execute_many, get_connection
from TSMGMT.utils import to_dt, datetimes_match, to_pst

oauth = OAuth()

# -- CONFIG --------------------------------------------------------------------
CALLS_PER_WINDOW = 45
WINDOW_SECONDS   = 10
MAX_RETRIES      = 5
INITIAL_BACKOFF  = 1 

def init_basecamp_oauth(app):
    oauth.init_app(app)
    oauth.register(
        name='basecamp',
        client_id=app.config['BASECAMP_CLIENT_ID'],
        client_secret=app.config['BASECAMP_CLIENT_SECRET'],

        # for the initial authorization redirect
        authorize_url='https://launchpad.37signals.com/authorization/new',
        authorize_params={'type': 'web_server'},

        # for exchanging the code for a token
        access_token_url='https://launchpad.37signals.com/authorization/token',
        access_token_params={'type': 'web_server'},

        # this is your Basecamp API base, using your account ID
        api_base_url=f"https://3.basecampapi.com/{app.config['BASECAMP_ACCOUNT_ID']}/",

        # ensure client_id/secret go in the POST body (not just the Authorization header)
        client_kwargs={
            'scope': 'default',
            'token_endpoint_auth_method': 'client_secret_post'
        }
    )

def connect_basecamp():
    # point at the actual Flask endpoint: work_status.callback
    redirect_uri = url_for('work_status.callback', _external=True)
    return oauth.basecamp.authorize_redirect(redirect_uri)

def basecamp_callback():
    """
    OAuth callback: exchange code for token and store in session.
    """
    token = oauth.basecamp.authorize_access_token()
    # Save the token in session or persist to DB keyed by user
    session['basecamp_token'] = token
    return redirect(url_for('work_status.index'))

def get_person_id_for_email(email, token):
    # 1) Try the cache
    row = execute_query(
        "SELECT person_id FROM BasecampStaffUsers WHERE email = ?",
        params=(email,)
    )
    if row:
        return row[0]['person_id']

    # 2) Fallback to the API
    people = _get_all_pages('people.json', token)
    for person in people:
        if person.get('email_address') == email:
            pid = person['id'] 

            # 3) Cache for next time
            execute_many(
                "INSERT INTO BasecampStaffUsers (email, person_id) VALUES (?,?);",
                [(email, pid)]
            )
            return pid

    return None  # not found

def get_all_todos():
    sql = """
        select distinct
            task_type,
            b.id,
            name,
            project_name,
            due_on,
            b.status,
            app_url,
            email,
            b.position,
            b.updated_at
        from [BasecampTasks] bt
        inner join BasecampTaskStatus b
            on bt.id = b.id
            and bt.email = b.user_email
        where user_email <> 'matt@cityspan.com'
	        and bt.completed = 0 
        order by email, b.updated_at desc
    """

    rows = execute_query(sql)

    # rows are CaseInsensitiveDicts with keys: id, name, due_on, status
    todos = []
    for row in rows:
        todos.append({
            'task_type': row['task_type'],
            'id':     row['id'],
            'name':   row['name'],
            'project_name': row['project_name'],
            'due_on': row.get('due_on'),
            'app_url': row.get('app_url'),
            'status': row['status'],
            'position': row['position'],
            'email': row['email'],
            'updated_at': row['updated_at'] if row['updated_at'] else None,
        })

    return todos

def get_user_todos(user, assignee_id=None):
    """
    Fetch the user's cached Basecamp todo items, optionally filtered by assignee.
    Syncs the cache before reading from the database.
    """
    token = session.get('basecamp_token')
    if not token:
        return []

    # Ensure local cache is up-to-date
    #sync_basecamp_cache(token)

    if assignee_id is None:
        # Determine assignee filter via people.json if not provided
        assignee_id = get_person_id_for_email(user.get('email'), token)
    
    # Build SQL to fetch todos from cached tables
    sql = (
        # task_type	task_id	title	url	due_on	assignee_id	email	task_status	status_position
        "select distinct task_type, project_name, id, name, due_on, status, app_url, email, position "
        "from BasecampTasks "
        "where assignee_id = ? "
        "   and due_on is not null "
        "   and isnull(completed, 1) <> 1 "  
        "   and isnull(status,'asf') <> 'hidden' "
        "order by position, due_on desc"
    )
    rows = execute_query(sql, params=(assignee_id))
    # rows are CaseInsensitiveDicts with keys: id, name, due_on, status
    todos = []
    for row in rows:
        todos.append({
            'task_type': row['task_type'],
            'id':     row['id'],
            'name':   row['name'],
            'project_name': row['project_name'],
            'due_on': row.get('due_on'),
            'app_url': row.get('app_url'),
            'status': row['status'],
            'assignees': []  # Assignees not stored in this query; can join if needed
        })
    return todos

# -- RATE-LIMIT + RETRYING GET -------------------------------------------------
@sleep_and_retry
@limits(calls=CALLS_PER_WINDOW, period=WINDOW_SECONDS)
def limited_get(url, token, headers=None):
    backoff = INITIAL_BACKOFF
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = oauth.basecamp.get(url, token=token, headers=headers or {})
            if resp.status_code == 429:
                ra = resp.headers.get('Retry-After')
                wait = int(ra) if ra and ra.isdigit() else WINDOW_SECONDS
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        except HTTPError:
            raise
        except (SSLError, ProtocolError, MaxRetryError) as e:
            last_exc = e
            if attempt == MAX_RETRIES:
                raise
            time.sleep(backoff)
            backoff *= 2
    raise last_exc

# -- PAGINATION W/ updated_since SUPPORT ---------------------------------------
def _get_all_pages(path, token, updated_since=None):
    items    = []
    base_url = oauth.basecamp.api_base_url.rstrip('/') + '/'
    # tack on updated_since if provided
    if updated_since:
        sep  = '&' if '?' in path else '?'
        path = f"{path}{sep}updated_since={updated_since}"
    url = path
    seen = set()

    while url and url not in seen:
        seen.add(url)
        resp = limited_get(url, token)
        if resp.status_code in (304, 404):
            break

        page = resp.json()
        if isinstance(page, list) and not page:
            break

        items.extend(page if isinstance(page, list) else [page])

        link = resp.headers.get('Link')
        url  = _parse_link_header(link, base_url) if link else None

    return items

def _parse_link_header(link_header, base_url):
    for part in link_header.split(','):
        if 'rel="next"' in part:
            m = re.search(r'<([^>]+)>', part)
            if m:
                href = m.group(1)
                return href[len(base_url):] if href.startswith(base_url) else href
    return None

# -- SYNC-STATE TABLE HELPERS --------------------------------------------------
def to_iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat() + 'Z'

def get_last_sync(resource: str) -> datetime:
    row = execute_query(
        "SELECT last_refreshed_at FROM dbo.BasecampSyncState WHERE resource = ?",
        params=[resource]
    )
    return to_dt(row[0]['last_refreshed_at']) if row else None

def set_last_sync(resource: str):
    now = datetime.utcnow()
    execute_query("""
        MERGE dbo.BasecampSyncState AS target
        USING (VALUES (?, ?)) AS src(resource, last_refreshed_at)
          ON target.resource = src.resource
        WHEN MATCHED THEN 
          UPDATE SET last_refreshed_at = src.last_refreshed_at
        WHEN NOT MATCHED THEN
          INSERT (resource, last_refreshed_at) VALUES (src.resource, src.last_refreshed_at);
    """, params=[resource, now])

# -- ORCHESTRATOR --------------------------------------------------------------
def sync_basecamp_cache_with_yield(token: str):
    # 1) Detect stale projects without writing:
    api_projects, stale_projects = get_stale_projects(token)
    total_steps = len(stale_projects) * 2
    yield f"PROGRESS_TOTAL:{total_steps}"

    # 2) Loop per project
    for proj, proj_since in stale_projects:
        name = proj.get('name', proj.get('id'))
        yield f"Syncing project '{name}'"

        # cards
        yield "  Syncing cards hierarchy..."
        sync_cards_hierarchy(token, proj, proj_since)
        yield "PROGRESS_STEP:1"

        # todos
        yield "  Syncing todos hierarchy..."
        sync_todos_hierarchy(token, proj, proj_since)
        yield "PROGRESS_STEP:1"

        # 3) Now that this project's children are done,
        _upsert_projects([proj])  # reuse your helper, passing a single-item list

        # 4) And stamp its sync state. 
        set_last_sync('projects')

        yield f"Project '{name}' updated."

    # 5) Finally, one last message
    yield "All done!"

# -- PROJECTS ------------------------------------------------------------------
def get_stale_projects(token):
    """
    Fetch all projects, compare against BasecampProjects,
    and return a list of (project_obj, updated_since_iso)
    without writing anything to the DB yet.
    """
    last  = get_last_sync('projects')
    since = to_iso(last) if last else None
    api_projects = _get_all_pages('projects.json', token, updated_since=since)

    # detect which ones actually changed
    rows   = execute_query("SELECT project_id, updated_at FROM BasecampProjects")
    db_map = {r['project_id']: to_dt(r['updated_at']) for r in rows}
    stale = []
    for p in api_projects:
        pid = p['id']
        upd = to_dt(p['updated_at'])
        if not datetimes_match(db_map.get(pid), upd):
            stale.append((p, to_iso(upd)))

        #new project, so add it to the DB so todos/cards can be added
        if p['id'] not in db_map:
            _upsert_projects([p])

    return api_projects, stale

def sync_projects(token):
    last  = get_last_sync('projects')
    since = to_iso(last) if last else None
    api   = _get_all_pages('projects.json', token, updated_since=since)
    stale = _upsert_projects(api)
    set_last_sync('projects')
    return stale

def _upsert_projects(api_projects):
    db = execute_query("SELECT project_id, updated_at FROM BasecampProjects")
    db_map = {r['project_id']: to_dt(r['updated_at']) for r in db}

    rows, stale = [], []
    for p in api_projects:
        pid  = p['id']
        upd  = to_dt(p['updated_at'])
        if not datetimes_match(db_map.get(pid), upd):
            rows.append((pid, p['name'], upd, pid, pid, p['name'], upd))
            stale.append((p, to_iso(upd)))

    if rows:
        execute_many("""
            IF EXISTS (SELECT 1 FROM BasecampProjects WHERE project_id=?)
                UPDATE BasecampProjects
                   SET name=?, updated_at=?
                 WHERE project_id=?;
            ELSE
                INSERT INTO BasecampProjects(project_id,name,updated_at)
                VALUES(?,?,?);
        """, rows)

    return stale

# -- TODOS HIERARCHY ----------------------------------------------------------
def sync_todos_hierarchy(token, proj, proj_since):
    stale_sets = sync_todosets(token, proj, proj_since)

    if stale_sets:
        for ts, ts_since in stale_sets:
            if ts:
                # 1) top-level lists
                stale_lists = sync_todolists(token, ts, ts_since)
                # 2) nested lists under those lists
                nested = sync_nested_todolists(token, stale_lists)
                # 3) combine and sync todos on all of them
                for tl, tl_since in (stale_lists + nested):
                    sync_todos(token, tl, tl_since)
    set_last_sync('todos')

def sync_todo_completions(token, proj):
    """
    For each stale project, fetch only new Todo recordings
    ('todo_completed' or 'todo_uncomplete') and update
    the completed flag in BasecampTodos.
    """
    project_id = proj['id']
    resource   = f"todo_recordings_{project_id}"

    # 1) read last sync time for this project's recordings
    last = get_last_sync(resource)
    since = to_iso(last) if last else None

    # 2) hit the recordings feed (bucket == project)
    path = f"projects/recordings.json?type=Todo&bucket={project_id}"
    recs = _get_all_pages(path, token, updated_since=since)

    # 3) process each recording
    for r in recs:
        if r['completed']:
            tid    = r.get('id')
            when   = to_dt(r.get('completion').get('created_at'))
            
            execute_query(
                "UPDATE BasecampTodos SET completed = 1, updated_at = ? WHERE todo_id = ?",
                params=[when, tid]
            )

    # 4) record that we've processed up through the latest recording
    set_last_sync(resource)

def sync_nested_todolists(token, parent_lists):
    """
    For each (todolist, since) in parent_lists, fetch its groups_url,
    upsert any nested lists with parent_list_id, and return
    a list of (nested_list_obj, nested_since_iso).
    """
    db   = execute_query("SELECT todolist_id, updated_at FROM BasecampTodoLists")
    dbm  = {r['todolist_id']: to_dt(r['updated_at']) for r in db}
    stale = []

    for tl, tl_since in parent_lists:
        url = tl.get('groups_url')
        if not url:
            continue

        nested = _get_all_pages(url, token, updated_since=tl_since)
        for nl in nested:
            nid    = nl['id']
            upd    = to_dt(nl['updated_at'])
            parent = nl['parent']['id']

            if not datetimes_match(dbm.get(nid), upd):
                # upsert the nested list, setting parent_list_id
                execute_many(
                    """
                    IF EXISTS (SELECT 1 FROM BasecampTodoLists WHERE todolist_id=?)
                      UPDATE BasecampTodoLists
                         SET title=?, updated_at=?, parent_list_id=?, todoset_id = null
                       WHERE todolist_id=?;
                    ELSE
                      INSERT INTO BasecampTodoLists
                          (todolist_id, title, updated_at, parent_list_id)
                      VALUES (?, ?, ?, ?);
                    """,
                   [(nid, nl['title'], upd, parent, nid, nid, nl['title'], upd, parent)]
                )
                stale.append((nl, to_iso(upd)))

    return stale

def sync_todosets(token, proj, proj_since):
    # find the todoset URL in the project's "dock" array
    urls = [m['url'] for m in proj.get('dock', []) if m['name']=='todoset' and m.get('enabled')]

    if not urls:
        return []

    stale = []
    for url in urls:
        # fetch the todoset metadata
        api = _get_all_pages(url, token, updated_since=proj_since)
        stale_ts = _upsert_todosets(api)

        if stale_ts:
            for ts in stale_ts:
                stale.append(ts)

    return stale

def _upsert_todosets(api_sets):
    db   = execute_query("SELECT todoset_id, updated_at FROM BasecampTodosets")
    dbm  = {r['todoset_id']: to_dt(r['updated_at']) for r in db}
    rows, stale = [], []

    for ts in api_sets:
        tsid, bucket = ts['id'], ts['bucket']['id']
        upd = to_dt(ts['updated_at'])
        if not datetimes_match(dbm.get(tsid), upd):
            rows.append((tsid, bucket, ts['title'], upd, tsid,
                         tsid, bucket, ts['title'], upd))
            stale.append((ts, to_iso(upd)))

    if rows:
        execute_many("""
            IF EXISTS (SELECT 1 FROM BasecampTodosets WHERE todoset_id=?)
              UPDATE BasecampTodosets
                 SET project_id=?, title=?, updated_at=?
               WHERE todoset_id=?;
            ELSE
              INSERT INTO BasecampTodosets(todoset_id,project_id,title,updated_at)
              VALUES(?,?,?,?);
        """, rows)

    return stale

def sync_todolists(token, ts, ts_since):
    url = ts.get('todolists_url')
    if not url:
        return []

    api = _get_all_pages(url, token, updated_since=ts_since)
    return _upsert_todolists(api)

def _upsert_todolists(api_lists):
    db   = execute_query("SELECT todolist_id, updated_at FROM BasecampTodoLists")
    dbm  = {r['todolist_id']: to_dt(r['updated_at']) for r in db}
    rows, stale = [], []

    for tl in api_lists:
        tlid = tl['id']
        upd  = to_dt(tl['updated_at'])
        parent_id = tl['parent']['id']
        if not datetimes_match(dbm.get(tlid), upd):
            rows.append((tlid, tl['title'], upd, parent_id, tlid,
                         tlid, tl['title'], upd, parent_id))
            stale.append((tl, to_iso(upd)))

    if rows:
        execute_many("""
            IF EXISTS (SELECT 1 FROM BasecampTodoLists WHERE todolist_id=?)
              UPDATE BasecampTodoLists
                 SET title=?, updated_at=?, todoset_id=?, parent_list_id = null
               WHERE todolist_id=?;
            ELSE
              INSERT INTO BasecampTodoLists(todolist_id,title,updated_at,todoset_id)
              VALUES(?,?,?,?);
        """, rows)

    return stale

def sync_todos(token, tl, _tl_since):
    """
    Sync *all* todos (active + completed) for this list, incrementally
    based on the last time *this* list was synced.
    """
    list_id = tl['id']
    resource = f"todos_{list_id}"

    # 1) read last sync for this list
    last = get_last_sync(resource)
    since = to_iso(last) if last else None

    # 2) fetch everything (completed + active) changed since then
    url = f"{tl['todos_url']}?status=all"
    api = _get_all_pages(url, token, updated_since=since)

    # 3) upsert and assignments
    bulk_merge_todos(api)

    # 4) handle completed todos
    url = f"{tl['todos_url']}?completed=true"
    api = _get_all_pages(url, token)
    bulk_merge_todos(api)

    # 4) record this sync time
    set_last_sync(resource)

# -- CARDS HIERARCHY ----------------------------------------------------------
def sync_cards_hierarchy(token, proj, proj_since):
    stale_tables = sync_cardtables(token, proj, proj_since)
    for ct, ct_since in stale_tables:
        stale_cols = sync_cardcolumns(token, ct, ct_since)
        for col, col_since in stale_cols:
            stale_cards = sync_cards(token, col, col_since)
            sync_cardsteps(token, stale_cards)

    set_last_sync('cards')

def sync_cardtables(token, proj, proj_since):
    url = next((m['url'] for m in proj.get('dock', [])
                if m['name']=='kanban_board' and m.get('enabled')), None)
    if not url:
        return []

    api = _get_all_pages(url, token, updated_since=proj_since)
    return _upsert_cardtables(api)

def _upsert_cardtables(api_tables):
    db   = execute_query("SELECT cardtable_id, updated_at FROM BasecampCardTables")
    dbm  = {r['cardtable_id']: to_dt(r['updated_at']) for r in db}
    rows, stale = [], []

    for t in api_tables:
        tid    = t['id']
        upd    = to_dt(t['updated_at'])
        bucket = t['bucket']['id']
        if not datetimes_match(dbm.get(tid), upd):
            rows.append((tid, bucket, t['title'], upd, tid,
                         tid, bucket, t['title'], upd))
            stale.append((t, to_iso(upd)))

    if rows:
        execute_many("""
            IF EXISTS (SELECT 1 FROM BasecampCardTables WHERE cardtable_id=?)
              UPDATE BasecampCardTables
                 SET project_id=?, title=?, updated_at=?
               WHERE cardtable_id=?;
            ELSE
              INSERT INTO BasecampCardTables(cardtable_id,project_id,title,updated_at)
              VALUES(?,?,?,?);
        """, rows)

    return stale

def sync_cardcolumns(token, ct, ct_since):
    db   = execute_query("SELECT cardcolumn_id, updated_at FROM BasecampCardColumns")
    dbm  = {r['cardcolumn_id']: to_dt(r['updated_at']) for r in db}
    stale = []

    # ct['lists'] is the array of column metadata (each has id, updated_at, url...)
    for col_meta in ct.get('lists', []):
        url = col_meta.get('url')
        if not url:
            continue

        # You can even use the column's own updated_at to filter downstream
        raw_upd = col_meta.get('updated_at')
        col_since = to_iso(to_dt(raw_upd)) if raw_upd else ct_since

        # Fetch only changed columns for this table
        api_cols = _get_all_pages(url, token, updated_since=col_since)

        # Upsert them and collect which ones were stale
        for c in api_cols:
            cid   = c['id']
            upd   = to_dt(c['updated_at'])
            if not datetimes_match(dbm.get(cid), upd):
                # this column is stale�upsert it
                execute_many(
                    """
                    IF EXISTS (SELECT 1 FROM BasecampCardColumns WHERE cardcolumn_id=?)
                      UPDATE BasecampCardColumns
                         SET cardtable_id=?, title=?, updated_at=?
                       WHERE cardcolumn_id=?;
                    ELSE
                      INSERT INTO BasecampCardColumns
                          (cardcolumn_id,cardtable_id,title,updated_at)
                      VALUES (?,?,?,?);
                    """,
                    [(cid, c['parent']['id'], c['title'], upd, cid,
                      cid, c['parent']['id'], c['title'], upd)]
                )
                # remember to recurse into cards for this column
                stale.append((c, to_iso(upd)))

    return stale

def _upsert_cardcolumns(api_cols):
    db   = execute_query("SELECT cardcolumn_id, updated_at FROM BasecampCardColumns")
    dbm  = {r['cardcolumn_id']: to_dt(r['updated_at']) for r in db}
    rows, stale = [], []

    for c in api_cols:
        cid    = c['id']
        upd    = to_dt(c['updated_at'])
        parent = c['parent']['id']
        if not datetimes_match(dbm.get(cid), upd):
            rows.append((cid, parent, c['title'], upd, cid,
                         cid, parent, c['title'], upd))
            stale.append((c, to_iso(upd)))

    if rows:
        execute_many("""
            IF EXISTS (SELECT 1 FROM BasecampCardColumns WHERE cardcolumn_id=?)
              UPDATE BasecampCardColumns
                 SET cardtable_id=?, title=?, updated_at=?
               WHERE cardcolumn_id=?;
            ELSE
              INSERT INTO BasecampCardColumns(cardcolumn_id,cardtable_id,title,updated_at)
              VALUES(?,?,?,?);
        """, rows)

    return stale

def sync_cards(token, col, col_since):
    """
    Fetch cards under the given column, upsert them (including completed),
    then refresh their assignees. Returns [(card_obj, since_iso), ...].
    """
    url = col.get('cards_url')
    if not url:
        return []

    # 1) Pull only cards updated since `col_since`
    api_cards = _get_all_pages(url, token, updated_since=col_since)

    # 2) Load existing state
    db   = execute_query("SELECT card_id, updated_at, completed FROM BasecampCards")
    db_map = {r['card_id']: (to_dt(r['updated_at']), bool(r['completed'])) for r in db}

    upsert_rows = []  # 1+5+1+6 = 13 params
    stale       = []

    for c in api_cards:
        cid      = c['id']
        upd_dt   = to_dt(c['updated_at'])
        parent   = c['parent']['id']
        due_on   = to_dt(c.get('due_on'))
        appurl   = c.get('app_url')
        completed = c.get('completed', False)

        old = db_map.get(cid, (None, None))
        if not datetimes_match(old[0], upd_dt) or old[1] != completed:
            # build param tuple:
            # 1) IF EXISTS WHERE card_id=?       -> cid
            # 2-6) UPDATE SET ...                  -> parent, title, updated_at, due_on, app_url, completed
            # 7) UPDATE WHERE card_id=?          -> cid
            # 8-13) INSERT VALUES(...)             -> cid, parent, title, updated_at, due_on, app_url, completed
            upsert_rows.append((
                cid,
                parent,        c['title'], upd_dt, due_on,   appurl,   int(completed),
                cid,
                cid,           parent,      c['title'], upd_dt, due_on,   appurl,   int(completed)
            ))
            stale.append((c, to_iso(upd_dt)))

    # 3) Bulk upsert BasecampCards
    if upsert_rows:
        execute_many(
            """
            IF EXISTS (SELECT 1 FROM BasecampCards WHERE card_id=?)
              UPDATE BasecampCards
                 SET cardcolumn_id=?, title=?, updated_at=?, due_on=?, app_url=?, completed=?
               WHERE card_id=?;
            ELSE
              INSERT INTO BasecampCards
                (card_id, cardcolumn_id, title, updated_at, due_on, app_url, completed)
              VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            upsert_rows
        )

    # 4) Refresh CardAssignees for stale cards
    if stale:
        ids = [c['id'] for c, _ in stale]
        ph  = ','.join('?' for _ in ids)

        # delete old assignments
        execute_query(
            f"DELETE FROM BasecampCardAssignees WHERE card_id IN ({ph})",
            params=ids
        )

        # insert fresh
        assign_rows = []
        for c, _ in stale:
            for a in c.get('assignees', []):
                assign_rows.append((c['id'], a['id']))

        if assign_rows:
            execute_many(
                "INSERT INTO BasecampCardAssignees (card_id, assignee_id) VALUES (?, ?)",
                assign_rows
            )

    return stale

def sync_cardsteps(token, stale_cards):
    """
    For each stale card (card_obj, since_iso), fetch its full payload
    (which includes 'steps'), upsert changed steps & assignees,
    and return [(step_obj, since_iso), ...] for downstream processing.
    """
    all_stale_steps = []

    for card, card_since in stale_cards:
        card_id = card['id']
        # 1) fetch the card with its steps
        resp = limited_get(
            f"buckets/{card['bucket']['id']}/card_tables/cards/{card_id}.json",
            token
        )
        resp.raise_for_status()
        data = resp.json()
        steps = data.get('steps', [])

        if not steps:
            continue

        # 2) load existing steps
        db   = execute_query("SELECT step_id, updated_at FROM BasecampCardStep")
        dbm  = {r['step_id']: to_dt(r['updated_at']) for r in db}

        upsert_rows = []  # 13 params per UPSERT
        ass_rows    = []

        for s in steps:
            sid      = s['id']
            upd_dt   = to_dt(s['updated_at'])
            parent   = card_id
            due_on   = to_dt(s.get('due_on'))
            appurl   = s.get('app_url')
            completed = s.get('completed', False)

            # 3) detect staleness
            if not datetimes_match(dbm.get(sid), upd_dt):
                # (1) WHERE?, (2-6)SET..., (7)WHERE?, (8-13)VALUES...
                upsert_rows.append((
                    sid,
                    parent, s['title'], upd_dt, due_on, appurl, int(completed),
                    sid,
                    sid, parent, s['title'], upd_dt, due_on, appurl, int(completed)
                ))
                all_stale_steps.append((s, to_iso(upd_dt)))

            # 4) rebuild assignees (only for non-completed steps)
            if not completed:
                for a in s.get('assignees', []):
                    ass_rows.append((sid, a['id']))

        # 5) bulk-upsert the steps
        if upsert_rows:
            execute_many(
                """
                IF EXISTS (SELECT 1 FROM BasecampCardStep WHERE step_id=?)
                  UPDATE BasecampCardStep
                     SET card_id=?, title=?, updated_at=?, due_on=?, app_url=?, completed=?
                   WHERE step_id=?;
                ELSE
                  INSERT INTO BasecampCardStep
                    (step_id, card_id, title, updated_at, due_on, app_url, completed)
                  VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                upsert_rows
            )

        # 6) refresh assignees
        if ass_rows:
            step_ids = sorted({sid for sid, _ in ass_rows})
            ph = ','.join('?' for _ in step_ids)
            execute_query(
                f"DELETE FROM BasecampCardStepAssignees WHERE step_id IN ({ph})",
                params=step_ids
            )
            execute_many(
                "INSERT INTO BasecampCardStepAssignees(step_id,assignee_id) VALUES(?,?)",
                ass_rows
            )

    return all_stale_steps

def bulk_merge_todos(
    api_todos: List[Tuple[int, int, str, Optional[str], datetime, bool, datetime]],
    section_name: str = "SMS",
    batch_size: int = 5000
) -> None:
    """
    Upsert a list of BasecampTodos in one shot via a temp table + single MERGE.
    todos_data must be tuples of
      (todo_id, todoset_id, content, app_url, due_on, completed, updated_at)
    """
    # 0) Extract todo data from api results
    db_todos = execute_query(f"SELECT todo_id, updated_at FROM BasecampTodos")
    db_todos_map = {row['todo_id']: to_dt(row['updated_at']) for row in db_todos}

    to_upsert = []
    for todo in api_todos:
        todo_id = todo.get('id')
        todo_list_id = todo.get('parent').get('id')
        content = todo.get('content')
        upd = to_dt(todo.get('updated_at'))
        due_on = to_dt(todo.get('due_on'))
        comp = todo.get('completed')
        app_url = todo.get('app_url')

        if not datetimes_match(db_todos_map.get(todo_id), upd):
            to_upsert.append((todo_id, todo_list_id, content, app_url, due_on, comp, upd))

    # 1) open one connection & cursor (temp tables live per-connection)
    conn = get_connection(section_name)
    cursor = conn.cursor()
    cursor.fast_executemany = True

    input_sizes = [
            (p.SQL_BIGINT,         0,   0),  
            (p.SQL_BIGINT,         0,   0),  
            (p.SQL_WLONGVARCHAR,  4000,  0),  
            (p.SQL_WLONGVARCHAR,  4000,  0), 
            (p.SQL_TYPE_TIMESTAMP, 27,   6),  
            (p.SQL_BIT,             0,   0),  
            (p.SQL_TYPE_TIMESTAMP, 27,   6),  
        ]

    cursor.setinputsizes(input_sizes)

    try:
        # 2) create staging table
        cursor.execute("""
        CREATE TABLE #tmp_todos (
            id int identity,
            todo_id     BIGINT       ,
            todolist_id  BIGINT       NULL,
            content     NVARCHAR(4000) NULL,
            app_url     NVARCHAR(4000) NULL,
            due_on      DATETIME2    NULL,
            completed   BIT          NULL,
            updated_at  DATETIME2    NULL
        );
        """)

        # 3) bulk-insert into staging
        insert_sql = """
        INSERT INTO #tmp_todos
          (todo_id, todolist_id, content, app_url, due_on, completed, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """
        for i in range(0, len(to_upsert), batch_size):
            batch = to_upsert[i : i + batch_size]
            cursor.executemany(insert_sql, batch)

        # 4) single MERGE from staging into real table
        merge_sql = """
        delete t
        from #tmp_todos t
        inner join (
            select todo_id, dense_rank() over (partition by todo_id order by id desc) as rnk
            from #tmp_todos
        ) dupes
            on t.todo_id = dupes.todo_id
            and dupes.rnk > 1;

        MERGE BasecampTodos AS target
        USING #tmp_todos AS src
          ON target.todo_id = src.todo_id
        WHEN MATCHED THEN
          UPDATE SET
            todolist_id = src.todolist_id,
            content    = src.content,
            app_url    = src.app_url,
            due_on     = src.due_on,
            completed  = src.completed,
            updated_at = src.updated_at
        WHEN NOT MATCHED BY TARGET THEN
          INSERT (todo_id, todolist_id, content, app_url, due_on, completed, updated_at)
          VALUES (src.todo_id, src.todolist_id, src.content, src.app_url, src.due_on, src.completed, src.updated_at);
        """
        cursor.execute(merge_sql)

        # 5) clean up and commit
        cursor.execute("DROP TABLE #tmp_todos;")
        conn.commit()

        # 6) wipe & re-insert assignees
        ids = [t['id'] for t in api_todos]
        if not ids:
            return

        # 3a) Delete old assignees
        placeholders = ','.join('?' for _ in ids)
        execute_query(
            f"DELETE FROM BasecampTodoAssignees WHERE todo_id IN ({placeholders})",
            params=ids
        )

        # 3b) Insert current assignees
        assignee_rows = []
        for t in api_todos:
            for a in t.get('assignees', []):
                assignee_rows.append((t['id'], a['id']))

        if assignee_rows:
            execute_many(
                "INSERT INTO BasecampTodoAssignees (todo_id, assignee_id) VALUES (?, ?)",
                assignee_rows
            )

    except p.Error:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()