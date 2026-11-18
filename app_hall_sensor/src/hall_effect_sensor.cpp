/*
 * hall: reads a digital Hall-effect sensor on IO3 (open-drain, pulled up to 3V3; sensor pulls
 * to GND when a magnetic field is detected). Sends 1.0 (field present) / 0.0 (absent) to the
 * dashboard (data ID "hall").
 *
 * Circuit:  3V3 --- R_PULLUP ---+--- Hall sensor (open-drain) --- GND
 *                                |
 *                           ADC ch2 (IO3 / GPIO3)
 *
 * No digital GPIO read is exposed to containers yet (src/bridge.cpp only has sds_adc_read_mv),
 * so this reads the pin as an analog voltage and thresholds it: near 0 mV = pulled to GND =
 * field detected, near 3300 mV = pulled up = no field. THRESHOLD_MV sits in between.
 *
 * Firmware imports (module "env", src/bridge.cpp):
 *   int  sds_adc_read_mv(int channel)            voltage in mV, <0 on error
 *   int  sds_publish(const char *id, double v)   one data point to the dashboard (TCP bridge)
 *   void sds_sleep_ms(int ms)
 * Parameters (env vars from the deployment): SIGNAL_ID, ADC_CHANNEL, THRESHOLD_MV, PERIOD_MS.
 *
 * Freestanding Wasm: no libc (matches untitled.cpp / pressure.cpp convention in this repo).
 */
#include <stdint.h>

__attribute__((import_module("env"), import_name("sds_adc_read_mv"))) int sds_adc_read_mv(int channel);
__attribute__((import_module("env"), import_name("sds_publish"))) int sds_publish(const char *id, double v);
__attribute__((import_module("env"), import_name("sds_sleep_ms"))) void sds_sleep_ms(int ms);
__attribute__((import_module("wasi_snapshot_preview1"), import_name("environ_sizes_get")))
int environ_sizes_get(uint32_t *count, uint32_t *size);
__attribute__((import_module("wasi_snapshot_preview1"), import_name("environ_get")))
int environ_get(char **env, char *buf);

#define SAMPLE_MS 10          /* one ADC sample every 10 ms */

static char id[32]       = "hall";
static int  channel      =  2;      /* IO3 = ESP32-S3 ADC1 channel 2 (ch n = GPIO n+1) */
static int  threshold_mv = 1650;   /* below = pulled to GND = field detected; above = pulled up */
static int  period_ms    = 500;    /* one published value every 500 ms = average of 50 samples */

/* ---- environment -------------------------------------------------------------- */
static char *envp[16];
static char envbuf[1024];

static const char *after(const char *s, const char *prefix)
{
	while (*prefix) {
		if (*s++ != *prefix++) {
			return 0;
		}
	}
	return s;
}

static int to_int(const char *s, int fallback)
{
	int v = 0, any = 0;

	for (; *s >= '0' && *s <= '9'; s++, any = 1) {
		v = v * 10 + (*s - '0');
	}
	return any ? v : fallback;
}

static void read_env(void)
{
	uint32_t n = 0, size = 0;
	const char *v;

	if (environ_sizes_get(&n, &size) || n > 16 || size > sizeof(envbuf) || environ_get(envp, envbuf)) {
		return;
	}
	for (uint32_t i = 0; i < n; i++) {
		if ((v = after(envp[i], "SIGNAL_ID=")) && *v) {
			int k = 0;
			while (v[k] && k < 31) { id[k] = v[k]; k++; }
			id[k] = 0;
		} else if ((v = after(envp[i], "ADC_CHANNEL="))) {
			channel = to_int(v, channel);
		} else if ((v = after(envp[i], "THRESHOLD_MV="))) {
			threshold_mv = to_int(v, threshold_mv);
		} else if ((v = after(envp[i], "PERIOD_MS="))) {
			period_ms = to_int(v, period_ms);
		}
	}
	if (period_ms < SAMPLE_MS) {
		period_ms = SAMPLE_MS;
	}
}

extern "C" void _start(void)
{
	read_env();
	const int per_publish = period_ms / SAMPLE_MS;

	for (;;) {
		long sum = 0;
		int good = 0;

		for (int i = 0; i < per_publish; i++) {
			int mv = sds_adc_read_mv(channel);
			if (mv >= 0) {
				sum += mv;
				good++;
			}
			sds_sleep_ms(SAMPLE_MS);
		}
		if (!good) {
			continue;                                   /* no reading: send nothing */
		}
		int avg_mv = (int)(sum / good);
		double detected = avg_mv < threshold_mv ? 1.0 : 0.0;

		sds_publish(id, detected);
	}
}