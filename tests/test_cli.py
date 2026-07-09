from atkdl16_cli.cli import main


def test_cli_list_dry_run_prints_supported_ids(capsys):
    rc = main(["--dry-run", "list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "1a86:ffcc" in out
    assert "1a86:6a6b" in out
    assert "04b4:6a6a" in out


def test_cli_info_dry_run_prints_get_device_data_frame(capsys):
    rc = main(["--dry-run", "info"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "GET_DEVICE_DATA" in out
    assert "00000000000000000a1001" in out


def test_cli_pwm_start_dry_run_prints_frame(capsys):
    rc = main(["--dry-run", "pwm", "start", "--channel", "0", "--freq", "1000", "--duty", "50"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "PWM_START" in out
    assert "170a11a086010050c30000" in out


def test_cli_pwm_stop_dry_run_prints_frame(capsys):
    rc = main(["--dry-run", "pwm", "stop", "--channel", "3"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "PWM_STOP" in out
    assert "170240" in out


def test_cli_stop_dry_run_prints_frame(capsys):
    rc = main(["--dry-run", "stop", "--channel", "2"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "STOP" in out
    assert "150202" in out
