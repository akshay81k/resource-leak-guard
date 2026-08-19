import java.io.*;

public class LeakOnExceptionPath {
    public void leakyMethod(String path) throws IOException {
        FileInputStream fis = new FileInputStream(path);
        int data = fis.read();
        fis.close();
    }
}
