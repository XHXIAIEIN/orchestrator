namespace Claw;

static class Program
{
    [STAThread]
    static void Main()
    {
        ApplicationConfiguration.Initialize();

        using var mutex = new Mutex(true, "Claw_Orchestrator_SingleInstance", out bool created);
        if (!created)
        {
            MessageBox.Show("Claw is already running.", "Claw", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }

        Application.Run(new TrayContext());
    }
}
