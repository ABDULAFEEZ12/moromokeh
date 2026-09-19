def safe_next_path(next_url):
    """Only ever redirect to a path on this site.

    Used anywhere a "where to go after this" value comes from user input
    (a query string or form field) - without this, a crafted link/form
    pointing `next` at an external URL becomes an open redirect. A same-site
    path always starts with exactly one "/"; "//evil.example" (protocol-
    relative) and "https://evil.example" are both rejected.
    """
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return None
