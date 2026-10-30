# Startskript der Test-SoftIOC
dbLoadRecords("/opt/softioc/test.db")
# Stresstest mit 1000 Kanälen WEISS:STRESS:* (erzeugt von scripts/gen-stress.py)
dbLoadTemplate("/opt/softioc/stress.substitutions")
iocInit()
dbpf WEISS:TEST:WAVE "[0,1,4,9,16,25,36,49,64,81]"
