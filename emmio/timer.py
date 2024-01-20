from pathlib import Path
from datetime import datetime
from collections import defaultdict
from matplotlib import pyplot as plt
from scipy.stats import norm
import numpy as np


NAMES = {
    "service__dm": {"name": "Duolingo App", "color": "green"},
    "service__d": {"name": "Duolingo Web", "color": "blue"},
    "service__k": {"name": "Kanji Teacher App", "color": "#880000"},
    "service__a": {"name": "AYOlingo", "color": "#880088"},
    "service_type__d_script": {"name": "Duolingo Script Web", "color": "red"},
    "service_type__d_grammar": {
        "name": "Duolingo Grammar Web",
        "color": "green",
    },
    "service_type__dm_script": {"name": "Duolingo Script App", "color": "blue"},
    "service_type__dm_grammar": {
        "name": "Duolingo Grammar App",
        "color": "orange",
    },
    "bonus__1": {"name": "Duolingo no bonus", "color": "blue"},
    "bonus__2": {"name": "Duolingo x2 bonus", "color": "red"},
}


def compute() -> None:
    xmin, xmax = None, None
    times = defaultdict(list)

    mode = "service"

    with Path("work/log.txt").open() as input_file:
        for line in input_file.readlines():
            line = line[:-1].strip()
            line = line.replace("  ", " ")
            line = line.replace("  ", " ")
            line = line.replace("  ", " ")
            date, course, value = line.split(" ")
            language, service = course.split(".")

            amount = 1
            if "/" in value:
                value, amount = value.split("/")
                amount = float(amount)
            if ":" in value:
                time = value.split(":")
                seconds = (int(time[0]) * 60 + int(time[1])) / amount
            else:
                seconds = float(value) / amount

            match mode:
                case "service_type":
                    type_: str = "script" if (len(language) == 4) else "grammar"
                    id_ = f"service_type__{service}_{type_}"
                case "service":
                    id_ = f"service__{service}"
                case "bonus":
                    if service in ("dm",):
                        rate = 2 if amount == 30 else 1
                        id_ = f"bonus__{rate}"
                    else:
                        id_ = None

            times[id_].append(seconds)
            if id_ in NAMES:
                xmin = min(xmin, seconds) if xmin else seconds
                xmax = max(xmax, seconds) if xmax else seconds

    font_name: str = "cmr10"  # "System Font"

    fig, ax1 = plt.subplots()
    ax2 = ax1.twinx()
    ax1.set_title("Action learning time")  # , font=font_name)
    ax1.set_xlabel("Time (s)")  # , font=font_name)
    ax1.set_ylabel("Number of sessions")  # , font=font_name)
    # ax1.set_xticks(font=font_name)
    # ax1.set_yticks(font=font_name)

    for id_, values in times.items():
        if id_ not in NAMES:
            continue

        # plt.hist(values, 19, color="#FFFFFF", edgecolor="#888877",
        # hatch='////')

        ax1.hist(
            values,
            label=NAMES[id_]["name"],
            fc=NAMES[id_]["color"],  # "none",
            range=(xmin, xmax),
            bins=20,
            alpha=0.2,
            color=NAMES[id_]["color"],
            # ec=SERVICES[course]["color"],
            # histtype="step",
            # linewidth=1,
        )

        mu, std = norm.fit(values)
        xs = np.linspace(xmin - 0.2, xmax + 0.2, 100)
        ys = norm.pdf(xs, mu, std)
        # ax2.plot(xs, ys, 'w', linewidth=4)
        # ax2.plot(xs, ys, 'k', linewidth=1)
        ax2.plot(xs, ys, linewidth=1, color=NAMES[id_]["color"])

    ax2.set_ylim([0, None])
    ax1.legend()
    plt.show()


def main() -> None:
    course = input("course > ")
    if not course:
        return
    language, service = course.split(".")
    assert 2 <= len(language) <= 4
    assert service
    while True:
        command = input("start [q?] > ")
        if command in ["q"]:
            break
        begin = datetime.now()
        print("Timer started.")
        input("stop > ")
        time = (datetime.now() - begin).total_seconds()
        print(f"{time} s lapsed.")
        with Path("work/log.txt").open("a+") as output_file:
            value = time
            output_file.write(
                f"{datetime.now().strftime('%Y-%m-%dT%H:%M')} {course} {value}\n"
            )


if __name__ == "__main__":
    main()
    compute()
