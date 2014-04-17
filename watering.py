import time, math, pprint, requests, smtplib
from yocto_api import *
from yocto_relay import *

LOCATION = "Cartigny,ch" # Use the nearest place or city
SMTP_SERVER = "mail.infomaniak.ch"
SMTP_PORT = 25 # typically 25, 465 or 587
SMTP_USER = "..."
SMTP_PASS = "..."
MAIL_FROM = "garden@yoctopuce.com"
MAIL_TO = "garden@yoctopuce.com"

class WeatherInfo:
    def __init__(self, record):
        self.time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record['dt']))
        self.temp = math.ceil((record['main']['temp'] - 273.15) * 10) / 10
        self.rain = 0
        pprint.pprint(vars(self))
        if 'rain' in record: self.rain = record['rain']['3h']

def currWeather():
    response = requests.get("http://api.openweathermap.org/data/2.5/weather?q="+LOCATION)
    if response.status_code != 200: return None
    return WeatherInfo(response.json())

def comingWeather():
    response = requests.get("http://api.openweathermap.org/data/2.5/forecast?q="+LOCATION)
    res = []
    if response.status_code == 200:
        now = time.time()
        for entry in response.json()['list']:
            # only use forecast for the coming 24h
            entryTime = entry['dt']
            if entryTime >= now+3600 and entryTime < now+86400:
                res.append(WeatherInfo(entry))
    return res

def sendMail(subject, body):
    message = "From: "+MAIL_FROM+"\r\nTo: "+MAIL_TO+"\r\n"+\
              "Subject: "+subject+"\r\n\r\n"+body
    mailServer = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
    mailServer.ehlo()
    mailServer.starttls()
    mailServer.ehlo()
    if SMTP_USER != "":
        mailServer.login(SMTP_USER, SMTP_PASS)
    mailServer.sendmail(MAIL_FROM, MAIL_TO, message)
    mailServer.close()

# Setup the API to use our USB relay
errmsg = YRefParam()
if YAPI.RegisterHub("usb", errmsg) != YAPI.SUCCESS:
    sys.exit("USB init error: "+errmsg.value)
relay = YRelay.FirstRelay()
if relay is None:
    sys.exit("Relay not found, check USB cable !")

# Show current local time on startup
now = time.localtime()
print("Current local time is %02d:%02d" % (now.tm_hour, now.tm_min))

# Startup default: assume there was no water yesterday
dryDays = 1

# Monitor weather conditions
history = []
while True:
    try:
        # wait for 58 seconds
        YAPI.Sleep(58*1000)
        now = time.localtime()
        print("Now %02d:%02d" % (now.tm_hour, now.tm_min))

        # Archive weather event records every 15 min
        if (now.tm_min % 15) == 0:
            YAPI.Sleep(3*1000)
            history.append(currWeather())

        # Evaluate the need for water at 7:30PM
        if now.tm_hour == 19 and now.tm_min == 15:
            # Integrate water history from recent events
            sum_rain = 0
            sum_etp = 0
            for event in history:
                if event.rain > 0:
                    sum_rain += event.rain / 12
                elif event.temp > 10:
                    sum_etp += 0.01 * (event.temp - 10)
            # Take a decision
            if sum_rain < 2:
                dryDays += 1
            period = "last "+str(len(history)/4)+"h"
            if sum_rain - sum_etp > 3:
                watering = False
                reason = str(sum_rain)+"mm rain in "+period
            elif sum_etp - sum_rain > 5:
                watering = True
                reason = str(sum_rain)+"mm water missing in "+period
            elif dryDays >= 3:
                watering = True
                reason = "No water for last "+str(dryDays)+" days"
            else:
                watering = False
                reason = "Enough water for now"
            # Cancel watering is rain is coming soon
            forecast = comingWeather()
            if watering:
                new_rain = 0
                for event in forecast:
                    new_rain += event.rain
                if new_rain >= 3:
                    watering = False
                    reason += " but "+str(new_rain)+"mm rain is coming"
            # Apply decision (open relay for 90 min to disable watering today)
            if not watering:
                relay.pulse(90*60*1000)
            # Keep me informed of what is going on
            subject = "Watering" if watering else "No watering"
            body = reason + ".\r\n\r\nWeather records:\r\n"
            for event in history:
                body += pprint.pformat(vars(event)) + "\r\n"
            body += "\r\nForecast:\r\n"
            for event in forecast:
                body += pprint.pformat(vars(event)) + "\r\n"
            sendMail(subject, body)
            # Clear history each time there has been water
            if watering or sum_rain > 3:
                history[:] = []
                dryDays = 0
    except:
        print("Unexpected error:", sys.exc_info()[0])
        pass
