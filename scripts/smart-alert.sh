#!/bin/bash
# Wird von smartd bei SSD-Problemen aufgerufen
~/scripts/notify.sh "da-hub: SSD-Warnung" "SMART-Fehler erkannt: ${SMARTD_MESSAGE}" urgent
