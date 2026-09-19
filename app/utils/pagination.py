import math


def paginate(collection, query, page, per_page, sort=None, projection=None):
    """Fetch one page of a Mongo query. Returns (docs, page, total_pages, total_count).

    Counting + fetching are two queries, but both are index-backed (see the
    indexes created in app/__init__.py) so this stays cheap even as the
    catalog grows - the page always requests only `per_page` documents,
    never the whole matching set.
    """
    total = collection.count_documents(query)
    total_pages = max(1, math.ceil(total / per_page))
    page = min(max(1, page), total_pages)

    cursor = collection.find(query, projection) if projection else collection.find(query)
    if sort:
        cursor = cursor.sort(sort)
    cursor = cursor.skip((page - 1) * per_page).limit(per_page)

    return list(cursor), page, total_pages, total
