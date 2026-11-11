# The keys live on three different controllers — and Volume Up is not one of them

`07-dead-ends.md` §D2 records that Volume Up/Down produced no readable input, and
its correction concluded that "the ABL never reaches its menu decision point".
The live device tree shows the key wiring, and it changes why that measurement
came out the way it did.

---

    10|## 1. Where each key actually is

```
/soc/qcom,spmi@c42d000/qcom,pmk8550@0/pon_hlos@1300/pwrkey
    linux,code = 116      KEY_POWER          PMIC PON block
/soc/qcom,spmi@c42d000/qcom,pmk8550@0/pon_hlos@1300/resin
    linux,code = 114      KEY_VOLUMEDOWN     PMIC PON block
/soc/gpio_keys/vol_up
    linux,code = 115      KEY_VOLUMEUP       SoC GPIO
    gpios      = <phandle 6 1>             -> PM8550 gpio 6
    debounce-interval = 15
    gpio-key,wakeup
```

with the pin confirmed on the PMIC side:

```
/soc/qcom,spmi@c42d000/qcom,pm8550@1/pinctrl@8800/key_vol_up/key_vol_up_default
    pins          = "gpio6"
    function      = "normal"
    input-enable, bias-pull-up, power-source 1
```

Three different arrangements:

| key | controller | read when |
|---|---|---|
| Power | PMIC **PON** | always — the PON block is in the always-on domain |
| Volume **Down** | PMIC **PON** (`resin`) | always |
| Volume **Up** | **PM8550 GPIO 6**, through `gpio_keys` | only once a driver enumerates it |

## 2. What this corrects

`07-dead-ends.md` §D2's correction argued, correctly, that Volume **Down** is
`pon_resin` and therefore cannot be board-mismatched. It then generalised:
"Volume Up is `<&pm8550_gpios 6>`, so that one genuinely can differ."

The live tree confirms that generalisation **for the stock board**: Volume Up is
PM8550 gpio 6. But it also shows the consequence that was not drawn:

**Volume Up is the only one of the three keys that needs a GPIO driver.** Power
and Volume Down are readable from the PON block with no driver at all. So when a
foreign ABL (the ROCKNIX build) runs, the two PON keys can still be seen by that
code if it polls PON, while Volume Up is invisible to anything that does not
configure PM8550 gpio 6 exactly as this board does.

That is the opposite of the earlier inference, which treated Volume Down as the
fragile one.

## 3. Why this matters for the vendor procedure

`43-vendor-entry-procedure.md` records Lenovo's own instruction: power off, hold
**Volume Up**, connect the cable. If Volume Up is a PM8550 GPIO rather than a PON
input, then that key is read by whichever code brings up the PMIC GPIOs — not by
the PON latch.

Two consequences, both testable and both cheap:

1. the key must be held **before** the code that configures that GPIO runs, which
   is consistent with the vendor wording ("keep Volume up key pressing and then
   connect device");
2. a device in a state where the PMIC GPIOs are never configured will not see
   Volume Up at all — which is exactly the state this tablet is in after a failed
   ABL, and would explain "no readable input" for Volume Up specifically.

Note that Volume Down, being `resin`, does **not** have that problem — so a
procedure that relies on Volume Down has a better chance of being seen than one
that relies on Volume Up, in the broken-ABL state.

## 4. What is still unknown

- Whether the vendor's "Volume up" instruction refers to the PM8550 gpio 6 path or
  to something in the boot ROM that reads the PMIC differently. The DT describes
  Android's view, not the boot ROM's.
- Whether the boot ROM reads PM8550 gpio 6 at all. The stock ABL and Android do;
  the ROM is a different piece of code and no document here shows its key handling.
- Whether a PON-based key (Volume Down) can trigger the same entry. Untested, and
  worth trying precisely because it does not depend on GPIO configuration.

## 5. Practical ranking of what to try, given this

```
1. power off, hold Volume Down, connect cable      PON-based, no GPIO needed
2. power off, hold Volume Up,   connect cable      the vendor's wording
3. power off, hold both,        connect cable      covers either path
```

All three are free and need only the connector. Step 1 is the one this analysis
predicts has the best chance in the current state, and it is *not* the procedure
the vendor card describes — which is why it is worth doing even though the card
says otherwise.
