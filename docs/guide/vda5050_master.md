start the master

```bash
export VDA5050_MAP_PATH=$PWD/demos/warehouse/map/warehouse.lif.json
ros2 run vda5050_master_ros2 example_master
```

```bash
ros2 service call /vda5050_master/onboard_agv_batch vda5050_master_ros2/srv/OnboardAGVBatch "$(cat $PWD/demos/warehouse/agv/onboard_agv_batch.yaml)"
```
