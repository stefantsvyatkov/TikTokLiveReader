"""The add-on's translation, set up once; every module imports ``_`` from here.
Outside NVDA (tests, tools) the strings stay English."""

try:
	import addonHandler
except ImportError:
	addonHandler = None

if addonHandler is not None:
	# Puts NVDA's ``_`` for the add-on's catalogue into this module.
	addonHandler.initTranslation()

if "_" not in globals():

	def _(text):
		return text


__all__ = ["_"]
