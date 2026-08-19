import java.io.*;

public class NoLeakExplicitClose {
    public void safeMethod(String path) throws IOException {
        FileInputStream fis = new FileInputStream(path);
        fis.close();
    }
}
