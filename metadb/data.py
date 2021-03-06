import json
import uuid
import pytz
import datetime

from sqlalchemy.sql import text

from . import db


def add_token(admin=False):
    """ Add a new token to the database and return it
        Arguments:
          admin: True if this token has admin privileges
    """
    query = text("""
        INSERT INTO token (token, admin)
             VALUES (:token, :admin)""")
    with db.engine.begin() as connection:
        token = str(uuid.uuid4())
        result = connection.execute(query, {"token": token, "admin": admin})
        return token


def remove_token(token):
    try:
        uuid.UUID(token, version=4)
    except ValueError:
        return
    query = text("""
        DELETE FROM token
              WHERE token = :token""")
    with db.engine.begin() as connection:
        connection.execute(query, {"token": token})


def get_tokens():
    query = text("""
        SELECT token::text
             , admin
          FROM token
      ORDER BY added""")
    with db.engine.begin() as connection:
        rows = connection.execute(query)
        return [dict(r) for r in rows.fetchall()]


def get_token(token):
    try:
        uuid.UUID(token, version=4)
    except ValueError:
        return {}
    query = text("""
        SELECT token::text
             , admin
          FROM token
         WHERE token = :token""")
    with db.engine.begin() as connection:
        result = connection.execute(query, {"token": token})
        if result.rowcount:
            return dict(result.fetchone())
        else:
            return {}


def add_source(name):
    query = text("""
        INSERT INTO source (name)
             VALUES (:name)
          RETURNING id""")
    with db.engine.begin() as connection:
        result = connection.execute(query, {"name": name})
        id = result.fetchone()[0]
        return {"name": name, "id": id}


def _add_recording_mbids(connection, mbids):
    check_query = text("""
        SELECT mbid
          FROM recording
         WHERE mbid = :mbid""")
    insert_query = text("""
        INSERT INTO recording (mbid)
             VALUES (:mbid)""")
    ret = []
    for mbid in mbids:
        result = connection.execute(check_query, {"mbid": mbid})
        if not result.rowcount:
            connection.execute(insert_query, {"mbid": mbid})
            ret.append(mbid)
    return ret


def add_recording_mbids(mbids):
    """ Add some recording musicbrainzids to the recording table.
        Returns mbids which were added.
    """
    with db.engine.begin() as connection:
        return _add_recording_mbids(connection, mbids)


def get_recording_mbids():
    query = text("""
        SELECT mbid::text
          FROM recording
      ORDER BY added""")
    with db.engine.begin() as connection:
        result = connection.execute(query)
        return [dict(r) for r in result.fetchall()]


def load_source(name):
    query = text("""
        SELECT id
             , name
          FROM source
         WHERE name = :name""")
    with db.engine.begin() as connection:
        result = connection.execute(query, {"name": name})
        row = result.fetchone()
        if row:
            return {"id": row.id, "name": row.name}
    return None


def add_scraper(source, module, mb_type, version, description):
    if mb_type not in ["recording", "release_group"]:
        raise ValueError("Invalid mb_type. Must be one of [recording, release_group]")

    query = text("""
        INSERT INTO scraper (source_id, module, mb_type, version, description)
             VALUES (:source_id, :module, :mb_type, :version, :description)
          RETURNING id
        """)
    with db.engine.begin() as connection:
        data = {"source_id": source["id"],
                "module": module,
                "mb_type": mb_type,
                "version": version,
                "description": description}
        result = connection.execute(query, data)
        row = result.fetchone()

        data["id"] = row.id
        return data


def load_scrapers_for_source(source):
    query = text("""
        SELECT id
             , source_id
             , module
             , mb_type
             , version
             , description
          FROM scraper
         WHERE source_id = :source_id
        """)
    with db.engine.begin() as connection:
        result = connection.execute(query, {"source_id": source["id"]})
        rows = result.fetchall()
        ret = []
        for r in rows:
            ret.append({"id": r.id,
                        "source_id": r.source_id,
                        "module": r.module,
                        "mb_type": r.mb_type,
                        "version": r.version,
                        "description": r.description})
        return ret


def load_latest_scraper_for_source(source):
    query = text("""
        SELECT id
             , source_id
             , version
             , mb_type
             , module
             , description
          FROM scraper
         WHERE source_id = :source_id
      ORDER BY version DESC
         LIMIT 1
        """)
    with db.engine.begin() as connection:
        result = connection.execute(query, {"source_id": source["id"]})
        row = result.fetchone()
        if row:
            return {"id": row.id,
                    "source_id": row.source_id,
                    "module": row.module,
                    "mb_type": row.mb_type,
                    "version": row.version,
                    "description": row.description}
    return None


def add_item(scraper, mbid, data):
    with db.engine.begin() as connection:
        return _add_item_w_connection(connection, scraper, mbid, data)


class JsonDateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        return json.JSONEncoder.default(self, obj)


def _add_item_w_connection(connection, scraper, mbid, data):
    check_item_query = text("""
        SELECT *
          FROM item
         WHERE mbid = :mbid
           AND scraper_id = :scraper_id
        """)

    item_query = text("""
        INSERT INTO item (scraper_id, mbid)
             VALUES (:scraper_id, :mbid)
          RETURNING id
        """)

    item_data_query = text("""
        INSERT INTO item_data (item_id, data)
             VALUES (:item_id, :data)
        """)

    check_result = connection.execute(check_item_query,
                                      {"scraper_id": scraper["id"],
                                       "mbid": mbid})

    if not check_result.rowcount:
        result = connection.execute(item_query, {"scraper_id": scraper["id"],
                                                 "mbid": mbid})
        row = result.fetchone()
        id = row.id
        if data:
            if isinstance(data, dict) or isinstance(data, list):
                data = json.dumps(data, cls=JsonDateTimeEncoder)
            connection.execute(item_data_query, {"item_id": id,
                                                 "data": data})

        return True
    else:
        return False


def get_unprocessed_recordings_for_scraper(scraper, mbid=None):
    querytxt = """
        SELECT recording.mbid::text
             , recording_meta.name
             , recording_meta.artist_credit
          FROM recording
          JOIN recording_meta
         USING (mbid)
     LEFT JOIN recording_redirect rr
         USING (mbid)
     LEFT JOIN item
            ON recording.mbid = item.mbid
           AND item.scraper_id = :scraper_id
         WHERE item.mbid IS NULL
           AND rr.mbid IS NULL
    """
    params = {"scraper_id": scraper["id"]}
    if mbid is not None:
        querytxt += """AND recording.mbid = :mbid"""
        params["mbid"] = mbid
    with db.engine.begin() as connection:
        result = connection.execute(text(querytxt), params)
        return [dict(r) for r in result]


def get_unprocessed_release_groups_for_scraper(scraper, mbid=None):
    querytxt = """
        SELECT release_group.mbid::text
             , release_group_meta.name
             , release_group_meta.artist_credit
             , release_group_meta.first_release_date
          FROM release_group
          JOIN release_group_meta
         USING (mbid)
     LEFT JOIN item
            ON release_group.mbid = item.mbid
           AND item.scraper_id = :scraper_id
         WHERE item.mbid IS NULL
    """
    params = {"scraper_id": scraper["id"]}
    if mbid is not None:
        querytxt += """AND release_group.mbid = :mbid"""
        params["mbid"] = mbid
    with db.engine.begin() as connection:
        result = connection.execute(text(querytxt), params)
        return [dict(r) for r in result]


def get_recordings_missing_meta():
    query = text("""
        SELECT recording.mbid::text
          FROM recording
     LEFT JOIN recording_meta
         USING (mbid)
     LEFT JOIN recording_redirect
            ON recording.mbid = recording_redirect.mbid
         WHERE recording_meta.mbid IS NULL
           AND recording_redirect.mbid IS NULL""")
    with db.engine.begin() as connection:
        result = connection.execute(query)
        return [r[0] for r in result.fetchall()]


def load_item(mbid, source_name):
    source = load_source(source_name)
    scraper = load_latest_scraper_for_source(source)
    query = text("""
        SELECT item.id,
               item.mbid,
               item.added,
               item_data.data
          FROM item
     LEFT JOIN item_data
            ON item_data.item_id = item.id
         WHERE item.mbid = :mbid
           AND item.scraper_id = :scraper_id
        """)
    with db.engine.begin() as connection:
        result = connection.execute(query, {"scraper_id": scraper["id"],
                                            "mbid": mbid})
        row = result.fetchone()
        if row:
            return {"id": row.id, "mbid": row.mbid, "added": row.added,
                    "data": row.data}

    return None


def _get_recording_meta(connection, recording_mbid):
    # We want to return the timezone always in UTC, regardless of how it's stored in
    # the database, but if you specify a timezone, pg won't return it in the data,
    # so we add utc back on before returning it.
    query = text("""
      SELECT mbid::text
           , name
           , artist_credit
           , last_updated AT TIME ZONE 'UTC' AS last_updated
        FROM recording_meta
      WHERE mbid = :mbid""")
    result = connection.execute(query, {"mbid": recording_mbid})
    row = result.fetchone()
    if row:
        row = dict(row)
        lu = row.get("last_updated")
        if lu:
            row["last_updated"] = lu.replace(tzinfo=pytz.utc)
    return row


def get_recording_meta(recording_mbid):
    with db.engine.begin() as connection:
        return _get_recording_meta(connection, recording_mbid)


def musicbrainz_check_mbid_redirect(query_mbid, actual_mbid):
    """Check if we have redirected an mbid"""
    if query_mbid == actual_mbid:
        return

    #
    check_query = text("""
        SELECT *
          FROM recording_redirect
         WHERE mbid = :mbid
           AND new_mbid = :new_mbid""")

    insert_redirect = text("""
        INSERT INTO recording_redirect (mbid, new_mbid)
             VALUES (:mbid, :new_mbid)""")

    params = {"mbid": query_mbid, "new_mbid": actual_mbid}
    with db.engine.begin() as connection:
        res = connection.execute(check_query, params)
        if not res.rowcount:
            _add_recording_mbids(connection, [actual_mbid])
            connection.execute(insert_redirect, params)


def cache_musicbrainz_metadata(recording):
    """
    Convert metadata from the musicbrainz scraper into the metadata tables

    recording_meta
    recording_release_group
    release_group
    release_group_meta
    :param recording:
    :return:
    """

    with db.engine.begin() as connection:
        _add_recording_meta(connection, recording)
        for rg in recording["release_group_map"].values():
            _add_release_group_meta(connection, rg)
            _add_link_recording_release_group(connection, recording["mbid"], rg["mbid"])


def _add_recording_meta(connection, recording):
    """

    :param connection:
    :param recording: A dictionary of metadata with keys mbid, name, artist_credit, last_updated
                      last_updated must be a datetime object.
    :return:
    """

    existing = _get_recording_meta(connection, recording["mbid"])
    if existing:
        # If this recording exists, and has a last updated date equal to the one we
        # are trying to add, skip it
        existing_date = existing["last_updated"]
        current_date = recording["last_updated"]
        if existing_date >= current_date:
            return

        query = text("""
          UPDATE recording_meta
             SET name = :name
               , artist_credit = :ac
               , last_updated = :last_updated
           WHERE mbid = :mbid""")
        # Otherwise we perform an update
    else:
        # If the there is no existing recording, do an insert
        query = text("""
          INSERT INTO recording_meta (mbid, name, artist_credit, last_updated)
                              VALUES (:mbid, :name, :ac, :last_updated)""")

    connection.execute(query, {"mbid": recording["mbid"],
                               "name": recording["name"],
                               "ac": recording["artist_credit"],
                               "last_updated": recording["last_updated"]})


def get_release_group_meta(release_group_mbid):
    with db.engine.connect() as connection:
        return _get_release_group_meta(connection, release_group_mbid)


def _get_release_group_meta(connection, release_group_mbid):
    query = text("""
        SELECT mbid::text
             , name
             , artist_credit
             , first_release_date
             , last_updated AT TIME ZONE 'UTC' AS last_updated
          FROM release_group_meta
         WHERE mbid = :mbid""")
    result = connection.execute(query, {"mbid": release_group_mbid})
    row = result.fetchone()
    if row:
        row = dict(row)
        lu = row.get("last_updated")
        if lu:
            row["last_updated"] = lu.replace(tzinfo=pytz.utc)
    return row


def get_release_groups_for_recording(recording_mbid):
    query = text("""
        SELECT release_group_mbid::text
          FROM recording_release_group
         WHERE recording_mbid = :recording_mbid""")
    with db.engine.connect() as connection:
        result = connection.execute(query, {"recording_mbid": recording_mbid})
        ret = []
        for row in result.fetchall():
            ret.append(row[0])
        return ret


def _add_release_group_meta(connection, release_group):

    # See if the release group exists, and add it if not:
    existing_rg = _get_release_group_meta(connection, release_group["mbid"])
    if existing_rg:
        existing_last_updated = existing_rg["last_updated"]
        current_last_updated = release_group["last_updated"]
        # If `last_updated` hasn't changed, return
        if existing_last_updated >= current_last_updated:
            return

        # Otherwise update the existing meta
        query_rg_meta = text("""
                UPDATE release_group_meta
                   SET name = :name
                     , artist_credit = :artist_credit
                     , first_release_date = :first_release_date
                     , last_updated = :last_updated
                 WHERE mbid = :rg_mbid""")
    else:  # insert
        query_rg_meta = text("""
              INSERT INTO release_group_meta (mbid, name, artist_credit, first_release_date, last_updated)
                   VALUES (:rg_mbid, :name, :artist_credit, :first_release_date, :last_updated)""")

        query_insert_rg = text("""INSERT INTO release_group (mbid) VALUES (:mbid)""")
        connection.execute(query_insert_rg, {"mbid": release_group["mbid"]})

    # This will be an update or an insert
    connection.execute(query_rg_meta, {"rg_mbid": release_group["mbid"],
                                       "name": release_group["name"],
                                       "artist_credit": release_group["artist_credit"],
                                       "first_release_date": release_group["first_release_date"],
                                       "last_updated": release_group["last_updated"]})


def _add_link_recording_release_group(connection, recording_mbid, release_group_mbid):
    # See if there is a link between the RG and this recording_id
    query_check_recording_rg = text("""
      SELECT *
        FROM recording_release_group
       WHERE recording_mbid = :recording_mbid
         AND release_group_mbid = :release_group_mbid""")
    result_has_recording_rg = connection.execute(query_check_recording_rg,
                                                 {"recording_mbid": recording_mbid,
                                                  "release_group_mbid": release_group_mbid})
    if not result_has_recording_rg.rowcount:
        query_insert_recording_rg = text("""
          INSERT INTO recording_release_group (recording_mbid, release_group_mbid)
                                       VALUES (:recording_mbid, :release_group_mbid)""")
        connection.execute(query_insert_recording_rg, {"recording_mbid": recording_mbid,
                                                       "release_group_mbid": release_group_mbid})

