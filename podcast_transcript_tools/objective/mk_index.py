import os

from objective import Client


def create_transcript_index(objective_api_key: str) -> None:
    client = Client(api_key=objective_api_key)
    index = client.indexes.create_index(
        index_type="text",
        fields={"searchable": ["body"], "filterable": ["speaker", "title"]},
    )
    print(f"Started creating index ID: {index.id}")
    index.status(watch=True)


if __name__ == "__main__":
    print("Creating Objective index... watches creation, ctrl-c to exit")
    create_transcript_index(objective_api_key=os.environ["OBJECTIVE_KEY"])
