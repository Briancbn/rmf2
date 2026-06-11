import yaml

onboard_command = {"agvs": []}
for i in range(25):
    agv_info = {
        "manufacturer": "Manufacturer",
        "serial_number": str(i+1)
    }
    onboard_command["agvs"].append(agv_info)

with open("./onboard_agv_batch.yaml", "w") as f:
    yaml.dump(onboard_command, f)
