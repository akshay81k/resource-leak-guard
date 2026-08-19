import java.io.*;

public class LeakyMethod {
    public void leakyMethod(String path) throws IOException {
        FileInputStream fis = new FileInputStream(path);
        int data = fis.read();
        System.out.println(data);
    }
}
