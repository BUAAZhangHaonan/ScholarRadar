import argparse


def main():
    parser = argparse.ArgumentParser(prog="scholar-radar", description="ScholarRadar 研究工作台")
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    parser.parse_args()


if __name__ == "__main__":
    main()
