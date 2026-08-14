import psutil


def find_netease():

    result = []

    for p in psutil.process_iter(
        ["pid", "name"]
    ):

        try:

            name = p.info["name"]

            if (
                name
                and
                "cloudmusic"
                in
                name.lower()
            ):

                result.append(
                    p.info["pid"]
                )

        except:
            pass

    return result