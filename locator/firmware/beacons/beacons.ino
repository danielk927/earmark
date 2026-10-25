#include "beacon_runtime.h"

void setup() { beacon_runtime::begin(); }
void loop() { beacon_runtime::serviceSerial(); }
