import java.io.*;

public class ExplicitClose {
    public void safeMethod(String path) throws IOException {
        FileInputStream fis = new FileInputStream(path);
        int data = fis.read();
        fis.close();
    }
}
