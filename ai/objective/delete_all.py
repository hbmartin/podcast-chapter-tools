import os

from objective import Client


def obj_delete_all(objective_api_key: str) -> None:
    client = Client(api_key=objective_api_key)
    all_objects = client.object_store.list_all_objects()
    results = client.object_store.delete_objects(all_objects)
    print(results)


if __name__ == "__main__":
    obj_delete_all(objective_api_key=os.environ["OBJECTIVE_KEY"])
