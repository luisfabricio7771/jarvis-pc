// Local Windows launcher. Python and the project remain outside this executable.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Windows.Forms;
using Microsoft.Win32;

internal static class JarvisLauncher
{
    [STAThread]
    private static int Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        try
        {
            bool preview = args.Contains("--memory");
            bool providers = args.Contains("--providers");
#if MEMORY_PREVIEW
            preview = true;
#endif
#if PROVIDERS_PREVIEW
            providers = true;
#endif
            string entryPoint = Path.Combine(root, (preview || providers) ? "preview.py" : "main.py");
            if (!File.Exists(entryPoint))
                throw new FileNotFoundException("Conserva este ejecutable junto a los archivos de JARVIS.", entryPoint);

            string python = FindPython(root);
            if (python == null)
                throw new FileNotFoundException("No se encontró Python. Ejecuta launcher\\build.ps1 con el Python que tiene instaladas las dependencias de JARVIS.");

            var arguments = new List<string> { "-B", entryPoint };
            if (providers && !args.Contains("--providers")) arguments.Add("--providers");
            arguments.AddRange(args.Where(value => value != "--memory"));
            var start = new ProcessStartInfo
            {
                FileName = python,
                Arguments = String.Join(" ", arguments.Select(Quote)),
                WorkingDirectory = root,
                UseShellExecute = false,
                CreateNoWindow = true
            };
            using (Process process = Process.Start(start))
            {
                if (process == null)
                    throw new InvalidOperationException("Windows no pudo iniciar Python.");
            }
            return 0;
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "JARVIS — No se pudo iniciar", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }

    private static string FindPython(string root)
    {
        var candidates = new List<string>
        {
            Path.Combine(root, ".venv", "Scripts", "pythonw.exe"),
            Path.Combine(root, "venv", "Scripts", "pythonw.exe")
        };
        string configured = Path.Combine(root, "launcher", "python-path.txt");
        if (File.Exists(configured))
            candidates.Add(File.ReadAllText(configured).Trim());

        foreach (RegistryKey hive in new[] { Registry.CurrentUser, Registry.LocalMachine })
        {
            try
            {
                using (RegistryKey versions = hive.OpenSubKey(@"Software\Python\PythonCore"))
                {
                    if (versions == null) continue;
                    foreach (string version in versions.GetSubKeyNames().OrderByDescending(value => value))
                    {
                        using (RegistryKey install = versions.OpenSubKey(version + @"\InstallPath"))
                        {
                            if (install == null) continue;
                            string folder = install.GetValue("") as string;
                            if (!String.IsNullOrWhiteSpace(folder))
                                candidates.Add(Path.Combine(folder, "pythonw.exe"));
                        }
                    }
                }
            }
            catch (System.Security.SecurityException) { }
            catch (UnauthorizedAccessException) { }
        }

        foreach (string folder in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator))
            if (!String.IsNullOrWhiteSpace(folder))
                candidates.Add(Path.Combine(folder.Trim('"'), "pythonw.exe"));
        return candidates.FirstOrDefault(path => !String.IsNullOrWhiteSpace(path) && File.Exists(path));
    }

    // Quote one argument using the Windows command-line backslash/quote rules.
    private static string Quote(string value)
    {
        var result = new StringBuilder("\"");
        int slashes = 0;
        foreach (char character in value)
        {
            if (character == '\\') { slashes++; continue; }
            if (character == '"')
                result.Append('\\', slashes * 2 + 1);
            else
                result.Append('\\', slashes);
            result.Append(character);
            slashes = 0;
        }
        result.Append('\\', slashes * 2);
        result.Append('"');
        return result.ToString();
    }
}
