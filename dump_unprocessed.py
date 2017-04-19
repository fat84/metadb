# Dump items which haven't been processed to

import argparse
import csv

import metadb.data
import metadb.db
import metadb.log
import metadb.util
import config

metadb.db.init_db_engine(config.SQLALCHEMY_DATABASE_URI)


def dump_items(filename, data, keys):
    with open(filename, "w") as fp:
        dw = csv.DictWriter(fp, keys)
        dw.writeheader()
        dw.writerows(data)


def main(source_name, outname, perfile=None):
    source = metadb.data.load_source(source_name)
    scraper = metadb.data.load_latest_scraper_for_source(source)
    if scraper["mb_type"] == "recording":
        metadb.log.info("Dumping recording items")
        keys = ["mbid", "name", "artist_credit"]
        data = metadb.data.get_unprocessed_recordings_for_scraper(scraper)
    elif scraper["mb_type"] == "release_group"
        metadb.log.info("Dumping release_group items")
        keys = ["mbid", "name", "artist_credit", "first_release_date"]
        data = metadb.data.get_unprocessed_release_groups_for_scraper(scraper)

    if perfile:
        for i, chunk in enumerate(metadb.util.chunks(data, perfile), 1):
            filename = "%s-%d.csv" % (outname, i)
            dump_items(filename, chunk, keys)
    else:
        filename = "%s.csv" % (outname,)
        dump_items(filename, data, keys)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dump unprocessed items")
    parser.add_argument("--source", help="source name", required=True)
    parser.add_argument("--perfile", help="Number of items to dump per file", required=False)
    parser.add_argument("--outname", help="Filename template to write to (no extension)", required=True)

    args = parser.parse_args()
    main(args.source, args.outname, args.perfile)