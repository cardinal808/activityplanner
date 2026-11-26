"""Opdrachtregel: `python -m app.sync` (timer), `python -m app.sync test`,
`python -m app.sync --days 30` (geschiedenis ophalen)."""
import sys

from . import garmin, store


def main(argv):
    store.init()
    if not garmin.key_source():
        print("Geen Garmin-sleutel ingesteld; niets te doen.")
        return 0
    if argv[:1] == ["test"]:
        garmin.test()
        return 0
    days = 2
    if "--days" in argv:
        days = max(1, min(365, int(argv[argv.index("--days") + 1])))
    try:
        if "--days" in argv:
            store.put_kv("backfill", {"days": days})
            done, complete = garmin.sync(days=days, skip_complete=True)
        else:
            done, complete = garmin.sync(days=2)
            if complete:
                more = garmin.backfill()
                if more is not None:
                    print("Geschiedenis:", "compleet" if more else "deels, volgende keer verder")
        for d, errs in done:
            print(d, "OK" if not errs else "deels: " + "; ".join(errs))
        if not complete:
            print("Garmin-limiet bereikt; de timer gaat elk uur verder met de rest.")
    except garmin.GarminError as e:
        print("Fout:", e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
