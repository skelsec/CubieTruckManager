#!/usr/bin/env python
import multiprocessing
import os
import sys
import time
import logging
import logging.handlers
from SMSender import SMS, SendSMS
import subprocess
from subprocess import Popen, PIPE, STDOUT
import shlex



class BatteryMonitor(multiprocessing.Process):
	def __init__(self, notifyQueue):
		multiprocessing.Process.__init__(self)
		self.batteryLevelStatusFile = '/sys/class/power_supply/battery/capacity'
		self.batteryUsedStatusFile = '/sys/class/power_supply/battery/online'
		self.notifyLevels = []
		self.notifyQueue = notifyQueue
		self.shutdownLevel = 10
		self.batteryStatusCheckTimeout = 10
		self.previousBatteryLevel = 100
		self.isCharning = False
		self.isBatteryUsed = False


	def setup(self):
		self.previousBatteryLevel = self.getBatteryLevel()
		self.isBatteryUsed = self.getBatteryUsage()
		return

	def log(self, level, message):
		self.notifyQueue.put((level, self.name, message))

	def run(self):
		#delay the startup until the battery checking subsystem is fully active
		time.sleep(3*60)
		try:
			self.log('INFO','Starting...')
			self.setup()
			while True:
				batteryLevel = self.getBatteryLevel()
				#check if the board currently uses the battery
				self.isBatteryUsed = self.getBatteryUsage()
				if not self.isBatteryUsed:
					self.log('INFO','Running on external power.')
					time.sleep(10)
					continue


				self.log('DEBUG','Current battery level: %s%%' % (batteryLevel))
				if batteryLevel <= self.shutdownLevel:
					self.log('SMS','Battery level critically low (%s%%)! Shutting down system!' % (batteryLevel,))
					time.sleep(5)
					subprocess.call(shlex.split("shutdown now -h"))
					return

				if batteryLevel < self.previousBatteryLevel:
					self.isCharning = False
					self.notifyLevels.sort()
					for notifyLevel in self.notifyLevels:
						if self.previousBatteryLevel > notifyLevel and batteryLevel <= notifyLevel:
							self.log('SMS','Battery level is at %s%%' % (batteryLevel,))

				else:
					#battery is probably charging
					self.log('INFO','Battery is chargning.')
					self.isCharning = True

				self.previousBatteryLevel = batteryLevel

				time.sleep(self.batteryStatusCheckTimeout)
		except Exception as e:
			self.log('EXCEPTION','Exception in main loop. Data: %s' % (str(e),))

	def getBatteryLevel(self):
		batteryLevel = self.readFileBlocking(self.batteryLevelStatusFile)
		return int(batteryLevel)

	def getBatteryUsage(self):
		isBatteryUsed = self.readFileBlocking(self.batteryUsedStatusFile)
		return bool(isBatteryUsed)


	def readFileBlocking(self, filename):
		while True:
			try:
				with open(filename, 'rb') as f:
					return f.read()
			except:
				time.sleep(1)
				pass

class NotificationProcess(multiprocessing.Process):
	def __init__(self, notifyQueue):
		multiprocessing.Process.__init__(self)
		self.notifyQueue = notifyQueue
		self.notificationPhoneNumer = ''
		self.logger = ''

	def log(self, level, message):
		self.notifyQueue.put((level, self.name, message))

	def setup(self):
		self.logger = logging.getLogger('CubieTruckMonitor')
		self.logger.setLevel(logging.DEBUG)
		#self.logger.setLevel(logging.INFO)
		handler = logging.handlers.SysLogHandler(address = '/dev/log')
		formatter = logging.Formatter('%(asctime)s [CubieTruckMonitor] %(message)s', datefmt='%b %d %H:%M:%S')
		handler.setFormatter(formatter)
		self.logger.addHandler(handler)

	def run(self):
		try:
			self.log('INFO','Starting...')
			self.setup()
			while True:
				notification = self.notifyQueue.get()
				self.handleLog(notification)
		except Exception as e:
			self.log('EXCEPTION','Exception in main loop. Data:' % (str(e),))

	def handleLog(self, log):
		print log
		level, src, message = log
		#print '[%s][%s][%s] %s' % (datetime.utcnow(), level, src, message)
		if level == 'DEBUG':
			self.logger.debug('[%s] %s' % (src, message))
		elif level == 'INFO' or level == 'SMS':
			if self.notificationPhoneNumer != '' and 'SMSender' in sys.modules and level == 'SMS':
				try:
					self.sendSMS(log)
				except Exception as e:
					self.log('WARNNING','Failed to send SMS. Data:' % (str(e),))
			self.logger.info('[%s] %s' % (src, message))
		elif level == 'WARNING':
			self.logger.warning('[%s] %s' % (src, message))
		elif level == 'EXCEPTION':
			self.logger.warning('[%s] %s' % (src, message))

	def sendSMS(self, notification):
		sender = SendSMS()
		sms = SMS()
		sms.send_to.append(self.notificationPhoneNumer)
		sms.message = notification[2]
		sender.send(sms)


class FilesystemMonitor(multiprocessing.Process):
	def __init__(self, notifyQueue):
		multiprocessing.Process.__init__(self)
		self.notifyQueue = notifyQueue
		self.mountFile = '/proc/mounts'
		self.diskCleanupCMD = 'fsck -A -y'


	def log(self, level, message):
		self.notifyQueue.put((level, self.name, message))

	def setup(self):
		return

	def run(self):
		try:
			self.setup()
			while True:
				if self.checkMountOptions() != 'OK':
					self.forceFSCK()
					self.restartSystem()
				#time.sleep(10)
				return

		except Exception as e:
			self.log('EXCEPTION','Exception in main loop. Data: %s' % (e))

	def checkMountOptions(self):
		self.log('INFO','Checking filesystem mount options')
		with open(self.mountFile,'rb') as f:
			for line in f:
				line = line.strip()
				group,path,type,options,rest,rest2 = line.split(' ')
				if path == '/':
					for option in options.split(','):
						if option == 'ro':
							self.log('SMS','WARNING! Filesystem is mounted as read-only. This indictase a not clean shutdown')
							return 'ERR'
		return 'OK'



	def forceFSCK(self):
		self.log('INFO','Starting fsck...')
		try:
			from subprocess import DEVNULL # py3k
		except ImportError:
			DEVNULL = open(os.devnull, 'wb')

		p = Popen(shlex.split(self.diskCleanupCMD), stdin=PIPE, stdout=DEVNULL, stderr=STDOUT)
		p.wait()
		if p.returncode != 0:
			self.log('WARNING','WARNING! FSCK returned exit code %s' % (str(p.returncode),))
		else:
			self.log('INFO','FSCK finished sucsessfully')
		return

	def restartSystem(self):
		self.log('SMS','Restarting system after FSCK cleanup!')
		os.system('restart')
		return

if __name__ == '__main__':
	notifyQueue = multiprocessing.Queue()

	np = NotificationProcess(notifyQueue)
	np.daemon = True
	np.notificationPhoneNumer = 'XXXXXXXXXXXXXX'
	np.start()

	fm = FilesystemMonitor(notifyQueue)
	fm.daemon = True
	fm.start()


	bm = BatteryMonitor(notifyQueue)
	bm.daemon = True
	bm.notifyLevels.append(50)
	bm.notifyLevels.append(70)
	bm.start()

	notifyQueue.put(('SMS', 'MAIN', 'System started!'))

	while True:
		time.sleep(10)
