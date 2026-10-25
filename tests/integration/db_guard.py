"""Guard that keeps the destructive integration suite off real databases.

The suite truncates every app table before each test. Reading a dedicated
``TEST_DATABASE_URL`` already avoids the app's ``DATABASE_URL``; this check is
the second line of defence in case someone points it at a hosted project.
"""

from psycopg.conninfo import conninfo_to_dict

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def assert_local_database(url: str) -> None:
    """Raise ``RuntimeError`` unless every host in ``url`` is loopback.

    A missing host (Unix socket or libpq env defaults) is refused too: the
    target cannot be proven local. Only host names are echoed, never secrets.
    """
    host = conninfo_to_dict(url).get("host")
    hosts = [h.strip() for h in str(host).split(",")] if host else []
    if not hosts or any(h not in LOCAL_HOSTS for h in hosts):
        raise RuntimeError(
            f"refusing to run destructive integration tests against a non-local database "
            f"(host={host or 'unset'}); set TEST_DATABASE_URL to a local Supabase "
            f"(127.0.0.1, localhost or ::1)"
        )
